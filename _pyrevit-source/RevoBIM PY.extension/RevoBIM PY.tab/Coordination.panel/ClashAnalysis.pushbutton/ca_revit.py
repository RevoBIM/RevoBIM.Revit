# -*- coding: utf-8 -*-
"""Clash Analysis - reading the model: models, catalogues, clash detection,
marker families, worksets, levels and the CLASH- groups already placed.

Read only. Every write lives in ca_jobs.py.
"""
import ca_clr  # noqa: F401  (assembly references first)

from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    BooleanOperationsType, BooleanOperationsUtils, BuiltInParameter,
    CategoryType, CurveElement, Element, ElementId, ElementMulticategoryFilter,
    FamilyInstance, ImportInstance,
    FamilySymbol, FilteredElementCollector, FilteredWorksetCollector,
    GeometryInstance, Group, Level, ModelPathUtils, Options, RevitLinkInstance, Solid,
    SolidUtils, View3D, ViewDetailLevel, ViewPlan, ViewSchedule, WorksetKind, XYZ,
)

import ca_core as core

# Model categories with no solid of their own, or that only ever clash with
# everything (and so drown the report).
EXCLUDED_CATEGORIES = set([
    u'Levels', u'Grids', u'Rooms', u'Spaces', u'Areas', u'HVAC Zones',
    u'Cameras', u'Lines', u'Project Information', u'Materials', u'Views',
    u'Sheets', u'Scope Boxes', u'Reference Planes', u'Section Boxes',
    u'Point Clouds', u'RVT Links', u'Imports in Families', u'Model Groups',
    u'Detail Items', u'Center line', u'Center Line', u'Analytical Nodes',
    u'Mass', u'Shaft Openings', u'Electrical Circuits', u'Duct Systems',
    u'Piping Systems', u'Cable Tray Runs', u'Conduit Runs', u'Wires',
    u'Route Analysis', u'MEP Fabrication Containment Runs',
])

HOST_KEY = u'HOST'


# ======================================================================
# Small helpers that work on every release 2024 - 2027
# ======================================================================

def eid_value(element_id):
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        pass
    try:
        return getattr(element_id, 'IntegerValue')
    except Exception:
        return 0


def workset_int(workset_id):
    """WorksetId keeps IntegerValue on every release (it is not an ElementId)."""
    try:
        return getattr(workset_id, 'IntegerValue')
    except Exception:
        return -1


def bip(name):
    """BuiltInParameter member looked up when it is needed, never at load."""
    return getattr(BuiltInParameter, name, None)


def elem_name(element):
    if element is None:
        return u''
    try:
        return core.to_text(element.Name)
    except Exception:
        pass
    try:
        return core.to_text(Element.Name.GetValue(element))
    except Exception:
        return u''


def param_text(element, bip_name):
    try:
        member = bip(bip_name)
        if member is None:
            return u''
        p = element.get_Parameter(member)
        if p is None:
            return u''
        value = p.AsString()
        if value is None:
            value = p.AsValueString()
        return core.to_text(value)
    except Exception:
        return u''


def category_name(element):
    try:
        cat = element.Category
        if cat is None:
            return u''
        return core.to_text(cat.Name)
    except Exception:
        return u''


class TypeNames(object):
    """(family, type) per type id, looked up once per document."""

    def __init__(self, doc):
        self.doc = doc
        self.cache = {}

    def of(self, element):
        try:
            tid = element.GetTypeId()
        except Exception:
            tid = None
        key = eid_value(tid)
        if key in self.cache:
            return self.cache[key]
        fam = u''
        typ = u''
        etype = None
        if key > 0:
            try:
                etype = self.doc.GetElement(tid)
            except Exception:
                etype = None
        if etype is not None:
            try:
                fam = core.to_text(etype.FamilyName)
            except Exception:
                fam = u''
            typ = param_text(etype, 'SYMBOL_NAME_PARAM') or elem_name(etype)
        if not fam:
            fam = category_name(element)
        result = (fam, typ)
        self.cache[key] = result
        return result


# ======================================================================
# Models: the host and each loaded link instance
# ======================================================================

class Model(object):
    def __init__(self, key, label, doc, transform=None, link_id=None):
        self.key = key
        self.label = label
        self.doc = doc
        self.transform = transform
        self.link_id = link_id
        self.catalog = None

    def to_host(self, point):
        if self.transform is None:
            return (point.X, point.Y, point.Z)
        p = self.transform.OfPoint(point)
        return (p.X, p.Y, p.Z)


def central_path(doc):
    try:
        if not doc.IsWorkshared:
            return u''
        return core.to_text(ModelPathUtils.ConvertModelPathToUserVisiblePath(
            doc.GetWorksharingCentralModelPath()))
    except Exception:
        return u''


def list_models(doc):
    models = [Model(HOST_KEY, u'Host model - ' + core.to_text(doc.Title), doc)]
    seen = {}
    try:
        links = FilteredElementCollector(doc).OfClass(RevitLinkInstance)
    except Exception:
        links = []
    for link in links:
        try:
            ldoc = link.GetLinkDocument()
        except Exception:
            ldoc = None
        if ldoc is None:
            continue
        name = core.to_text(ldoc.Title)
        seen[name] = seen.get(name, 0) + 1
        key = u'LINK:' + name
        label = u'Link - ' + name
        if seen[name] > 1:
            key = u'{0}#{1}'.format(key, seen[name])
            label = u'{0} (copy {1})'.format(label, seen[name])
        try:
            tf = link.GetTotalTransform()
        except Exception:
            tf = None
        models.append(Model(key, label, ldoc, tf, link.Id))
    return models


def _listable(cat, model_type):
    """Revit's own model categories only (see core.is_model_category)."""
    try:
        cname = core.to_text(cat.Name)
        if cname in EXCLUDED_CATEGORIES or cname.startswith(u'Analytical'):
            return False
        return core.is_model_category(cname, eid_value(cat.Id) < 0,
                                      cat.Parent is not None,
                                      cat.CategoryType == model_type)
    except Exception:
        return False


def scan_catalog(model, log=None):
    """{category: {family: count}} of the model elements in a document."""
    if model.catalog is not None:
        return model.catalog
    names = TypeNames(model.doc)
    out = {}
    try:
        col = (FilteredElementCollector(model.doc)
               .WhereElementIsNotElementType()
               .WhereElementIsViewIndependent())
    except Exception as ex:
        if log:
            log(u'scan {0}: {1}'.format(model.key, ex))
        model.catalog = out
        return out
    model_type = CategoryType.Model
    verdict = {}
    for el in col:
        try:
            cat = el.Category
            if cat is None:
                continue
            ckey = eid_value(cat.Id)
            if ckey not in verdict:
                verdict[ckey] = _listable(cat, model_type)
            if not verdict[ckey]:
                continue
            if isinstance(el, (ImportInstance, CurveElement)):
                continue
            cname = core.to_text(cat.Name)
            fam = names.of(el)[0]
            slot = out.setdefault(cname, {})
            slot[fam] = slot.get(fam, 0) + 1
        except Exception:
            continue
    model.catalog = out
    if log:
        log(u'scan {0}: {1} categories'.format(model.key, len(out)))
    return out


def category_ids(doc, names):
    ids = []
    wanted = set(names)
    try:
        for cat in doc.Settings.Categories:
            try:
                if core.to_text(cat.Name) in wanted:
                    ids.append(cat.Id)
            except Exception:
                continue
    except Exception:
        pass
    return ids


# ======================================================================
# Gathering one side of a test
# ======================================================================

def _host_box(model, bb):
    raw = (bb.Min.X, bb.Min.Y, bb.Min.Z, bb.Max.X, bb.Max.Y, bb.Max.Z)
    if model.transform is None:
        return raw
    tf = model.transform

    def fn(pt):
        p = tf.OfPoint(XYZ(pt[0], pt[1], pt[2]))
        return (p.X, p.Y, p.Z)
    return core.transform_box(raw, fn)


BIG = 1.0e7


def _box_of(bbox, flat=False):
    """Axis aligned host box round a BoundingBoxXYZ (its transform applied).
    flat=True opens the box up and down (plan crop boxes)."""
    tf = bbox.Transform
    pts = []
    for x in (bbox.Min.X, bbox.Max.X):
        for y in (bbox.Min.Y, bbox.Max.Y):
            for z in (bbox.Min.Z, bbox.Max.Z):
                p = tf.OfPoint(XYZ(x, y, z))
                pts.append((p.X, p.Y, p.Z))
    box = core.box_from_points(pts)
    if flat:
        box = (box[0], box[1], -BIG, box[3], box[4], BIG)
    return box


def view_limit_box(view):
    """Fallback limit for linked models when Revit cannot filter a link by
    the view: a 3D view's section box, or a plan / section's crop box
    (plans open up and down). None = no limit."""
    try:
        if isinstance(view, View3D):
            if view.IsSectionBoxActive:
                return _box_of(view.GetSectionBox())
            return None
        if view.CropBoxActive and view.CropBox is not None:
            return _box_of(view.CropBox, flat=isinstance(view, ViewPlan))
    except Exception:
        pass
    return None


def run_scope(uiapp, test):
    """None for a whole-project run. For a current-view run: the view the
    clash test is limited to, and its level when the view is a floor plan
    (clash families placed from that run go on that level)."""
    if test.get('scope') != u'view':
        return None
    uidoc = uiapp.ActiveUIDocument
    view = uidoc.ActiveView
    level_id = None
    try:
        if isinstance(view, ViewPlan) and view.GenLevel is not None:
            level_id = view.GenLevel.Id
    except Exception:
        level_id = None
    return {
        'doc': uidoc.Document,
        'view_id': view.Id,
        'view_name': core.to_text(view.Name),
        'limit': view_limit_box(view),
        'level_id': level_id,
    }


def _collector(model, ids, scope, log):
    """(collector, limit_box). View scope: host elements the view shows,
    link elements the view shows (Revit 2024+ link collector), or - if that
    is refused - the whole link limited to the view's box."""
    cat_filter = ElementMulticategoryFilter(List[ElementId](ids))
    if scope is None:
        col = FilteredElementCollector(model.doc)
        return col.WherePasses(cat_filter).WhereElementIsNotElementType(), None
    if model.link_id is None:
        col = FilteredElementCollector(model.doc, scope['view_id'])
        return col.WherePasses(cat_filter).WhereElementIsNotElementType(), None
    try:
        col = FilteredElementCollector(scope['doc'], scope['view_id'], model.link_id)
        return col.WherePasses(cat_filter).WhereElementIsNotElementType(), None
    except Exception as ex:
        if log:
            log(u'{0}: view filter refused ({1}) - using the view box'.format(
                model.label, ex))
    col = FilteredElementCollector(model.doc)
    return (col.WherePasses(cat_filter).WhereElementIsNotElementType(),
            scope.get('limit'))


def gather(models, model_keys, keys, log=None, scope=None):
    """Items for one side: dicts with the element, its model, its names and
    its box in host coordinates. scope (from run_scope) limits every model
    to what the current view shows."""
    by_key = dict((m.key, m) for m in models)
    keys = set(keys)
    cats = sorted(set(core.split_key(k)[0] for k in keys))
    items = []
    for mk in model_keys:
        model = by_key.get(mk)
        if model is None:
            if log:
                log(u'model {0} is not loaded - skipped'.format(mk))
            continue
        ids = category_ids(model.doc, cats)
        if not ids:
            continue
        names = TypeNames(model.doc)
        try:
            col, limit = _collector(model, ids, scope, log)
        except Exception as ex:
            if log:
                log(u'gather {0}: {1}'.format(mk, ex))
            continue
        for el in col:
            try:
                cname = category_name(el)
                fam, typ = names.of(el)
                if not core.key_matches(keys, cname, fam):
                    continue
                bb = el.get_BoundingBox(None)
                if bb is None:
                    continue
                box = _host_box(model, bb)
                if limit is not None and not core.boxes_overlap(box, limit):
                    continue
                items.append({
                    'el': el, 'model': model, 'id': el.Id,
                    'uid': u'{0}:{1}'.format(model.key, eid_value(el.Id)),
                    'category': cname, 'family': fam, 'type': typ,
                    'box': box,
                })
            except Exception:
                continue
    return items


# ======================================================================
# Geometry
# ======================================================================

def _options():
    opts = Options()
    try:
        opts.DetailLevel = ViewDetailLevel.Fine
    except Exception:
        pass
    try:
        opts.IncludeNonVisibleObjects = False
        opts.ComputeReferences = False
    except Exception:
        pass
    return opts


def _walk(geo, out, depth=0):
    if geo is None or depth > 4:
        return
    for obj in geo:
        try:
            if isinstance(obj, Solid):
                if obj.Volume > 1e-9:
                    out.append(obj)
            elif isinstance(obj, GeometryInstance):
                _walk(obj.GetInstanceGeometry(), out, depth + 1)
        except Exception:
            continue


def _solid_box(solid):
    try:
        bb = solid.GetBoundingBox()
        tf = bb.Transform
        pts = []
        for c in core.box_corners((bb.Min.X, bb.Min.Y, bb.Min.Z,
                                   bb.Max.X, bb.Max.Y, bb.Max.Z)):
            p = tf.OfPoint(XYZ(c[0], c[1], c[2]))
            pts.append((p.X, p.Y, p.Z))
        return core.box_from_points(pts)
    except Exception:
        return None


class Geometry(object):
    """Solids per element in host coordinates, cached for the run."""

    MAX_SOLIDS = 60

    def __init__(self):
        self.opts = _options()
        self.cache = {}

    def solids(self, item):
        uid = item['uid']
        if uid in self.cache:
            return self.cache[uid]
        found = []
        try:
            _walk(item['el'].get_Geometry(self.opts), found)
        except Exception:
            found = []
        tf = item['model'].transform
        out = []
        for s in found[:self.MAX_SOLIDS]:
            try:
                if tf is not None:
                    s = SolidUtils.CreateTransformed(s, tf)
                out.append((s, _solid_box(s)))
            except Exception:
                continue
        self.cache[uid] = out
        return out


def intersection(geom, a, b, touch_ft, mode):
    """(point, volume_ft3, box, approx) for a real clash, else None."""
    overlap = core.overlap_box(a['box'], b['box'])
    if overlap is None:
        return None
    if mode == 'box':
        if core.is_touching(overlap, touch_ft):
            return None
        return (core.box_centre(overlap), 0.0, overlap, True)
    sa = geom.solids(a)
    sb = geom.solids(b)
    failed = not sa or not sb
    parts = []
    boxes = []
    volume = 0.0
    for solid_a, box_a in sa:
        for solid_b, box_b in sb:
            if box_a is not None and box_b is not None and \
                    not core.boxes_overlap(box_a, box_b):
                continue
            try:
                res = BooleanOperationsUtils.ExecuteBooleanOperation(
                    solid_a, solid_b, BooleanOperationsType.Intersect)
            except Exception:
                failed = True
                continue
            try:
                if res is None or res.Volume <= 1e-9:
                    continue
                c = res.ComputeCentroid()
                parts.append(((c.X, c.Y, c.Z), res.Volume))
                volume += res.Volume
                rb = _solid_box(res)
                if rb is not None:
                    boxes.append(rb)
            except Exception:
                failed = True
    if parts:
        box = core.box_from_points(
            [(bx[0], bx[1], bx[2]) for bx in boxes] +
            [(bx[3], bx[4], bx[5]) for bx in boxes]) if boxes else overlap
        if core.is_touching(box, touch_ft):
            return None
        return (core.weighted_centroid(parts), volume, box, False)
    if failed:
        # Revit could not intersect these solids - fall back to the boxes
        if core.is_touching(overlap, touch_ft):
            return None
        return (core.box_centre(overlap), 0.0, overlap, True)
    return None


def related_uids(item, cache):
    """Elements a clash with this one should not count: MEP neighbours it is
    connected to, and the family it is nested in or nests."""
    uid = item['uid']
    if uid in cache:
        return cache[uid]
    out = set()
    el = item['el']
    mk = item['model'].key
    managers = []
    try:
        cm = getattr(el, 'ConnectorManager', None)
        if cm is not None:
            managers.append(cm)
    except Exception:
        pass
    try:
        mep = getattr(el, 'MEPModel', None)
        if mep is not None and mep.ConnectorManager is not None:
            managers.append(mep.ConnectorManager)
    except Exception:
        pass
    for cm in managers:
        try:
            for conn in cm.Connectors:
                try:
                    if not conn.IsConnected:
                        continue
                    for ref in conn.AllRefs:
                        owner = ref.Owner
                        if owner is not None:
                            out.add(u'{0}:{1}'.format(mk, eid_value(owner.Id)))
                except Exception:
                    continue
        except Exception:
            continue
    if isinstance(el, FamilyInstance):
        try:
            sup = el.SuperComponent
            if sup is not None:
                out.add(u'{0}:{1}'.format(mk, eid_value(sup.Id)))
        except Exception:
            pass
        try:
            for sid in el.GetSubComponentIds():
                out.add(u'{0}:{1}'.format(mk, eid_value(sid)))
        except Exception:
            pass
    out.discard(uid)
    cache[uid] = out
    return out


def side_info(item):
    return {
        'uid': item['uid'], 'model_key': item['model'].key,
        'model': item['model'].label, 'id': eid_value(item['id']),
        'eid': item['id'] if item['model'].key == HOST_KEY else None,
        'category': item['category'], 'family': item['family'],
        'type': item['type'],
    }


def run_test(models, test, log=None, scope=None):
    """Run one clash test. scope comes from run_scope (None = whole project).
    Returns {'clashes', 'a_count', 'b_count', 'candidates', 'approx',
    'scope', 'view_level'}."""
    a_items = gather(models, test['a_models'], test['a_keys'], log, scope)
    b_items = gather(models, test['b_models'], test['b_keys'], log, scope)
    if log:
        log(u'test "{0}" ({1}): {2} elements in A, {3} in B'.format(
            test['name'], scope['view_name'] if scope else u'whole project',
            len(a_items), len(b_items)))
    touch_ft = core.mm_to_ft(max(0.0, float(test.get('touch_mm', 0) or 0)))
    pairs = core.candidate_pairs([i['box'] for i in a_items],
                                 [i['box'] for i in b_items], pad=0.0)
    geom = Geometry()
    rel_cache = {}
    seen = set()
    clashes = []
    approx = 0
    for ia, ib in pairs:
        a = a_items[ia]
        b = b_items[ib]
        if a['uid'] == b['uid']:
            continue
        key = core.pair_key(a['uid'], b['uid'])
        if key in seen:
            continue
        seen.add(key)
        if test.get('skip_connected', True):
            if b['uid'] in related_uids(a, rel_cache) or \
                    a['uid'] in related_uids(b, rel_cache):
                continue
        try:
            hit = intersection(geom, a, b, touch_ft, test.get('mode', 'solid'))
        except Exception as ex:
            if log:
                log(u'pair {0} / {1}: {2}'.format(a['uid'], b['uid'], ex))
            continue
        if hit is None:
            continue
        point, volume, box, is_approx = hit
        if is_approx and test.get('mode') != 'box':
            approx += 1
        clashes.append({
            'a': side_info(a), 'b': side_info(b), 'point': point,
            'volume': volume, 'size': core.box_extents(box),
            'approx': is_approx,
        })
    if log:
        log(u'test "{0}": {1} candidate pairs, {2} clashes ({3} approx)'.format(
            test['name'], len(pairs), len(clashes), approx))
    return {'clashes': clashes, 'a_count': len(a_items),
            'b_count': len(b_items), 'candidates': len(pairs),
            'approx': approx,
            'scope': scope['view_name'] if scope else u'',
            'view_level': scope['level_id'] if scope else None}


# ======================================================================
# Marker families, worksets, levels
# ======================================================================

PLACEABLE = (u'OneLevelBased', u'WorkPlaneBased')


def marker_symbols(doc):
    """[(label, symbol)] for families that can be dropped at a point,
    Generic Models first."""
    out = []
    try:
        col = FilteredElementCollector(doc).OfClass(FamilySymbol)
    except Exception:
        return out
    for sym in col:
        try:
            cat = sym.Category
            if cat is None or cat.CategoryType != CategoryType.Model:
                continue
            fam = sym.Family
            placement = core.to_text(fam.FamilyPlacementType)
            if placement not in PLACEABLE:
                continue
            label = u'{0} : {1} : {2}'.format(
                core.to_text(cat.Name), core.to_text(fam.Name), elem_name(sym))
            out.append((label, sym))
        except Exception:
            continue
    out.sort(key=lambda r: (0 if r[0].startswith(u'Generic Models') else 1,
                            r[0].lower()))
    return out


def user_worksets(doc):
    """[(name, WorksetId)] - empty when the model is not workshared."""
    try:
        if not doc.IsWorkshared:
            return []
    except Exception:
        return []
    out = []
    try:
        for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset):
            out.append((core.to_text(ws.Name), ws.Id))
    except Exception:
        pass
    out.sort(key=lambda r: r[0].lower())
    return out


def workset_name(doc, element):
    try:
        if not doc.IsWorkshared:
            return u''
        return core.to_text(doc.GetWorksetTable().GetWorkset(element.WorksetId).Name)
    except Exception:
        return u''


def level_elevation(level):
    try:
        return level.ProjectElevation
    except Exception:
        try:
            return level.Elevation
        except Exception:
            return 0.0


def levels(doc):
    out = []
    try:
        for lvl in FilteredElementCollector(doc).OfClass(Level):
            out.append((lvl, level_elevation(lvl)))
    except Exception:
        pass
    return out


def family_of(symbol):
    try:
        return core.to_text(symbol.Family.Name)
    except Exception:
        return u''


def is_work_plane_based(symbol):
    try:
        return core.to_text(symbol.Family.FamilyPlacementType) == u'WorkPlaneBased'
    except Exception:
        return False


def find_schedule(doc, name):
    try:
        for vs in FilteredElementCollector(doc).OfClass(ViewSchedule):
            if not vs.IsTemplate and core.to_text(vs.Name) == name:
                return vs
    except Exception:
        pass
    return None


def family_comments(doc, family_name):
    """Comments of every placed instance of the family (for the column width)."""
    out = []
    try:
        col = (FilteredElementCollector(doc).OfClass(FamilyInstance)
               .WhereElementIsNotElementType())
    except Exception:
        return out
    for inst in col:
        try:
            if core.to_text(inst.Symbol.Family.Name) != family_name:
                continue
            out.append(param_text(inst, 'ALL_MODEL_INSTANCE_COMMENTS'))
        except Exception:
            continue
    return out


def family_points(doc, family_name):
    """Bounding-box centre of every placed instance of the family: where
    clash families already sit."""
    out = []
    try:
        col = (FilteredElementCollector(doc).OfClass(FamilyInstance)
               .WhereElementIsNotElementType())
    except Exception:
        return out
    for inst in col:
        try:
            if core.to_text(inst.Symbol.Family.Name) != family_name:
                continue
            bb = inst.get_BoundingBox(None)
            if bb is None:
                continue
            out.append(core.box_centre((bb.Min.X, bb.Min.Y, bb.Min.Z,
                                        bb.Max.X, bb.Max.Y, bb.Max.Z)))
        except Exception:
            continue
    return out


PLAN_TYPES = (u'FloorPlan', u'EngineeringPlan')


def plan_level_key(view):
    """eid of the level a floor plan is cut on, or None for any other view."""
    try:
        if isinstance(view, ViewPlan) and not view.IsTemplate and \
                view.GenLevel is not None:
            return eid_value(view.GenLevel.Id)
    except Exception:
        pass
    return None


def floor_plans(doc):
    """[{'id', 'name', 'level', 'level_key', 'kind'}] every floor plan."""
    out = []
    try:
        col = FilteredElementCollector(doc).OfClass(ViewPlan)
    except Exception:
        return out
    for v in col:
        try:
            if v.IsTemplate or core.to_text(v.ViewType) not in PLAN_TYPES:
                continue
            lvl = v.GenLevel
            out.append({'id': v.Id, 'name': core.to_text(v.Name),
                        'level': elem_name(lvl) if lvl is not None else u'',
                        'level_key': eid_value(lvl.Id) if lvl is not None else None,
                        'kind': u'Structural' if core.to_text(v.ViewType) ==
                        u'EngineeringPlan' else u'Floor plan'})
        except Exception:
            continue
    return out


def isolate_info(doc, active_view, member_ids):
    """Where the clash spheres of a group can be isolated."""
    level_ids = {}
    keys = []
    cat_ids = []
    for mid in member_ids:
        el = doc.GetElement(mid)
        if el is None:
            continue
        lid = None
        try:
            lid = el.LevelId
        except Exception:
            lid = None
        if lid is None or eid_value(lid) < 0:
            for name in ('FAMILY_LEVEL_PARAM', 'INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM'):
                try:
                    p = el.get_Parameter(bip(name))
                    if p is not None and eid_value(p.AsElementId()) >= 0:
                        lid = p.AsElementId()
                        break
                except Exception:
                    continue
        if lid is not None and eid_value(lid) >= 0:
            level_ids[eid_value(lid)] = lid
            keys.append(eid_value(lid))
        try:
            if el.Category is not None and \
                    eid_value(el.Category.Id) not in [eid_value(c) for c in cat_ids]:
                cat_ids.append(el.Category.Id)
        except Exception:
            pass
    level_key = core.most_common(keys)
    level_id = level_ids.get(level_key)
    active_key = plan_level_key(active_view)
    return {
        'members': [m for m in member_ids if doc.GetElement(m) is not None],
        'cat_ids': cat_ids,
        'level_key': level_key,
        'level_name': level_name(doc, level_id) if level_id is not None else u'',
        'active_name': core.to_text(active_view.Name),
        'active_id': active_view.Id,
        'active_ok': core.isolate_here(active_key, level_key),
        'views': floor_plans(doc),
    }


def views_3d(doc):
    """[(name, ViewId)] every 3D view that is not a template, by name."""
    out = []
    try:
        for v in FilteredElementCollector(doc).OfClass(View3D):
            try:
                if not v.IsTemplate:
                    out.append((core.to_text(v.Name), v.Id))
            except Exception:
                continue
    except Exception:
        pass
    out.sort(key=lambda r: r[0].lower())
    return out


def user_name(doc):
    try:
        return core.to_text(doc.Application.Username)
    except Exception:
        return u''


def boxes_of(doc, ids):
    out = []
    for i in ids:
        try:
            el = doc.GetElement(i)
            bb = el.get_BoundingBox(None) if el is not None else None
            if bb is not None:
                out.append((bb.Min.X, bb.Min.Y, bb.Min.Z, bb.Max.X, bb.Max.Y, bb.Max.Z))
        except Exception:
            continue
    return out


def level_name(doc, level_id):
    try:
        return elem_name(doc.GetElement(level_id))
    except Exception:
        return u''


# ======================================================================
# CLASH- groups already in the model
# ======================================================================

def clash_groups(doc):
    """One record per CLASH- group type, newest first."""
    by_type = {}
    try:
        col = FilteredElementCollector(doc).OfClass(Group)
    except Exception:
        return []
    for grp in col:
        try:
            gtype = grp.GroupType
            name = elem_name(gtype)
            parsed = core.parse_clash_group_name(name)
            if parsed is None:
                continue
            key = eid_value(gtype.Id)
            rec = by_type.get(key)
            if rec is None:
                rec = {'type_id': gtype.Id, 'name': name, 'parsed': parsed,
                       'instances': [], 'member_count': 0,
                       'workset': workset_name(doc, grp)}
                by_type[key] = rec
            rec['instances'].append(grp.Id)
            try:
                rec['member_count'] += grp.GetMemberIds().Count
            except Exception:
                pass
        except Exception:
            continue
    rows = list(by_type.values())
    rows.sort(key=lambda r: r['parsed']['sort'], reverse=True)
    return rows


def group_members(doc, record):
    out = []
    for gid in record['instances']:
        try:
            grp = doc.GetElement(gid)
            for mid in grp.GetMemberIds():
                out.append(mid)
        except Exception:
            continue
    return out


def group_report(doc, record):
    """Detail rows for every marker in the group's instances."""
    names = TypeNames(doc)
    rows = []
    for mid in group_members(doc, record):
        el = doc.GetElement(mid)
        if el is None:
            continue
        fam, typ = names.of(el)
        level = u''
        try:
            lvl = doc.GetElement(el.LevelId)
            level = elem_name(lvl)
        except Exception:
            pass
        rows.append({
            'eid': mid, 'id': eid_value(mid), 'uid': core.to_text(el.UniqueId),
            'family_type': u'{0} : {1}'.format(fam, typ) if typ else fam,
            'comments': param_text(el, 'ALL_MODEL_INSTANCE_COMMENTS'),
            'level': level, 'workset': workset_name(doc, el),
        })
    rows.sort(key=lambda r: (r['comments'].lower(), r['id']))
    return rows
