# -*- coding: utf-8 -*-
"""Number Sequencer - everything that talks to Revit.

Reading the selection or a picked system, the connector graph, parameter
and tag choices, and the apply job. Every function that writes runs inside
the ExternalEvent handler (see nsq_window).
"""

import nsq_clr  # noqa: F401  (must stay the first import)

import math
import traceback

from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter, ElementId,
    Element, Transaction, SubTransaction, TransactionGroup, FamilySymbol,
    IndependentTag, Reference, TagOrientation, StorageType, SpecTypeId,
    WorksharingUtils, IFailuresPreprocessor, FailureProcessingResult,
    FailureSeverity, ConnectorType, ConnectorProfileType, Domain,
    LocationCurve, LocationPoint, FabricationPart, OverrideGraphicSettings, XYZ, BoundingBoxXYZ,
    FillPatternElement, TemporaryViewMode, ElementCategoryFilter,
    ElementMulticategoryFilter, View, View3D, ViewFamilyType, ViewFamily, ViewSheet,
)
from Autodesk.Revit.DB import Color as RevitColor
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

import nsq_core as core

# BuiltInCategory names - looked up at call time, never at load
WALK_CATS = [u"OST_DuctCurves", u"OST_DuctFitting", u"OST_DuctAccessory",
             u"OST_FlexDuctCurves", u"OST_DuctTerminal",
             u"OST_FabricationDuctwork", u"OST_PlaceHolderDucts"]
EQUIP_CAT = u"OST_MechanicalEquipment"
NETWORK_LIMIT = 20000


# ============================================================
# Small helpers
# ============================================================

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


def id_list(ids):
    lst = List[ElementId]()
    for i in ids:
        lst.Add(i)
    return lst


def bic_int(name):
    b = getattr(BuiltInCategory, name, None)
    if b is None:
        return None
    try:
        return int(b)
    except Exception:
        return None


def cat_int(elem):
    try:
        return eid_value(elem.Category.Id)
    except Exception:
        return None


def cat_label(elem):
    try:
        return elem.Category.Name
    except Exception:
        return u""


def bic_name_of(elem, names):
    ci = cat_int(elem)
    for n in names:
        if bic_int(n) == ci:
            return n
    return None


def known_cats():
    names = list(WALK_CATS) + [EQUIP_CAT]
    for kind in sorted(core.KINDS):
        for part in (u"walk", u"through", u"ends"):
            for n in core.KINDS[kind][part]:
                if n not in names:
                    names.append(n)
    return names


def host_cat_name(elem):
    return bic_name_of(elem, known_cats()) or cat_label(elem)


def elem_name(elem):
    if elem is None:
        return u""
    try:
        return elem.Name
    except Exception:
        pass
    try:
        return Element.Name.GetValue(elem)
    except Exception:
        return u""


def _bip_text(elem, name):
    bip = getattr(BuiltInParameter, name, None)
    if bip is None:
        return u""
    try:
        p = elem.get_Parameter(bip)
        if p is None:
            return u""
        return p.AsValueString() or p.AsString() or u""
    except Exception:
        return u""


def family_type(doc, elem):
    fam = u""
    typ = u""
    if isinstance(elem, FabricationPart):
        for attr in (u"ProductLongDescription", u"ProductName",
                     u"ProductShortDescription", u"Alias"):
            try:
                v = getattr(elem, attr)
                if v:
                    fam = u"{0}".format(v)
                    break
            except Exception:
                pass
        for attr in (u"ProductSizeDescription", u"Size"):
            try:
                v = getattr(elem, attr)
                if v:
                    typ = u"{0}".format(v)
                    break
            except Exception:
                pass
    if not fam:
        fam = _bip_text(elem, u"ELEM_FAMILY_PARAM")
    if not typ:
        typ = _bip_text(elem, u"ELEM_TYPE_PARAM")
    if not fam or not typ:
        try:
            t = doc.GetElement(elem.GetTypeId())
        except Exception:
            t = None
        if t is not None:
            if not fam:
                try:
                    fam = t.FamilyName or u""
                except Exception:
                    fam = u""
            if not typ:
                typ = elem_name(t)
    return cat_label(elem), fam, typ


# ============================================================
# Connectors
# ============================================================

def connector_manager(elem):
    try:
        cm = elem.ConnectorManager
        if cm is not None:
            return cm
    except Exception:
        pass
    try:
        mm = elem.MEPModel
        if mm is not None:
            return mm.ConnectorManager
    except Exception:
        pass
    return None


def is_physical(conn):
    try:
        t = conn.ConnectorType
    except Exception:
        return False
    for bad in (u"Logical", u"Reference", u"Invalid", u"NodeReference"):
        m = getattr(ConnectorType, bad, None)
        if m is not None and t == m:
            return False
    try:
        d = conn.Domain
        for bad in (u"DomainElectrical", u"DomainCableTrayConduit"):
            m = getattr(Domain, bad, None)
            if m is not None and d == m:
                return False
    except Exception:
        pass
    return True


def iter_connectors(elem):
    cm = connector_manager(elem)
    if cm is None:
        return []
    out = []
    try:
        for c in cm.Connectors:
            if is_physical(c):
                out.append(c)
    except Exception:
        pass
    return out


def conn_area(conn):
    try:
        if conn.Shape == getattr(ConnectorProfileType, u"Round", None):
            r = conn.Radius
            return math.pi * r * r
        return conn.Width * conn.Height
    except Exception:
        return 0.0


def _xyz(p):
    try:
        return (p.X, p.Y, p.Z)
    except Exception:
        return None


def conn_refs(conn):
    out = []
    try:
        for r in conn.AllRefs:
            if is_physical(r):
                out.append(r)
    except Exception:
        pass
    return out


def has_duct_connectors(elem):
    return len(iter_connectors(elem)) > 0


# ============================================================
# Reading what to number
# ============================================================

def expand_selection(doc, ids):
    """Selected ids -> elements to number. A selected duct system expands
    to its network; anything with no duct connectors is dropped."""
    out = []
    seen = set()

    def add(e):
        k = eid_value(e.Id)
        if k in seen or not has_duct_connectors(e):
            return
        seen.add(k)
        out.append(e)

    for eid in ids:
        e = doc.GetElement(eid)
        if e is None:
            continue
        if has_duct_connectors(e):
            add(e)
            continue
        for attr in (u"DuctNetwork", u"Elements"):
            try:
                net = getattr(e, attr)
            except Exception:
                net = None
            if net is None:
                continue
            try:
                for m in net:
                    add(m)
            except Exception:
                pass
            break
    return out


def walk_ints():
    return set([i for i in [bic_int(n) for n in WALK_CATS] if i is not None])


def collect_network(doc, start, limit=NETWORK_LIMIT):
    """Everything connected to start through duct connectors, staying on
    ducts, fittings, accessories, flex, terminals and fabrication ductwork.
    Equipment is a boundary - never walked through."""
    walk = walk_ints()
    out = [start]
    seen = set([eid_value(start.Id)])
    queue = [start]
    while queue and len(out) < limit:
        e = queue.pop(0)
        for c in iter_connectors(e):
            for r in conn_refs(c):
                try:
                    o = r.Owner
                except Exception:
                    continue
                if o is None:
                    continue
                k = eid_value(o.Id)
                if k in seen or cat_int(o) not in walk:
                    continue
                seen.add(k)
                out.append(o)
                queue.append(o)
    return out


def read_network(doc, elems, log):
    """Elements -> everything the window needs, keyed by id value."""
    eq = bic_int(EQUIP_CAT)
    keys = set([eid_value(e.Id) for e in elems])
    nodes = {}
    rows = []
    idmap = {}
    hostcat = {}
    labels = {}
    sysname = {}
    for e in elems:
        k = eid_value(e.Id)
        idmap[k] = e.Id
        cat, fam, typ = family_type(doc, e)
        rows.append((k, cat, fam, typ))
        hostcat[k] = host_cat_name(e)
        sysname[k] = _bip_text(e, u"RBS_SYSTEM_NAME_PARAM")
        labels[k] = u"{0} : {1} : {2}".format(cat, fam, typ)
        conns = []
        for c in iter_connectors(e):
            links = []
            equipment = False
            external = False
            for r in conn_refs(c):
                try:
                    o = r.Owner
                except Exception:
                    continue
                if o is None:
                    continue
                ok = eid_value(o.Id)
                if ok == k:
                    continue
                if ok in keys:
                    links.append((ok, r.Id))
                else:
                    external = True
                    if cat_int(o) == eq:
                        equipment = True
            try:
                direction = _xyz(c.CoordinateSystem.BasisZ)
            except Exception:
                direction = None
            conns.append(core.Conn(c.Id, conn_area(c), _xyz(c.Origin),
                                   direction, links, equipment, external))
        nodes[k] = core.Node(k, conns, is_equipment=(cat_int(e) == eq),
                             label=labels[k])
    links = sum([len(c.links) for n in nodes.values() for c in n.conns]) // 2
    butted = core.link_open_ends(nodes, core.OPEN_END_TOL_MM / 304.8)
    log.add(u"read {0} elements: {1} connections in Revit, {2} more joined where open ends "
            u"touch (parts butted but never connected)".format(len(nodes), links, butted))
    return {u"nodes": nodes, u"rows": rows, u"idmap": idmap,
            u"hostcat": hostcat, u"labels": labels, u"sysname": sysname}


# ============================================================
# Parameters
# ============================================================

def _is_yes_no(p):
    try:
        dt = p.Definition.GetDataType()
        return dt.TypeId == SpecTypeId.Boolean.YesNo.TypeId
    except Exception:
        return False


def _is_builtin(p):
    try:
        bip = p.Definition.BuiltInParameter
        return u"{0}".format(bip) != u"INVALID"
    except Exception:
        return False


def _storage(p):
    try:
        st = p.StorageType
        if st == getattr(StorageType, u"String"):
            return u"text"
        if st == getattr(StorageType, u"Integer"):
            if _is_yes_no(p) or _is_builtin(p):
                return None  # built-in integers (workset, phase...) are not numbers
            return u"integer"
    except Exception:
        pass
    return None


def param_map(elems):
    """Writable text / integer instance parameters per element.
    Returns (storages {name: 'text'|'integer'}, per_elem {key: [names]})."""
    storages = {}
    per_elem = {}
    for e in elems:
        names = []
        try:
            params = list(e.Parameters)
        except Exception:
            params = []
        for p in params:
            try:
                if p.IsReadOnly:
                    continue
                st = _storage(p)
                if st is None:
                    continue
                name = p.Definition.Name
            except Exception:
                continue
            if not name or name in names:
                continue
            names.append(name)
            storages.setdefault(name, st)
        per_elem[eid_value(e.Id)] = names
    return storages, per_elem


def read_param_info(elem, name):
    if elem is None:
        return None
    try:
        p = elem.LookupParameter(name)
    except Exception:
        p = None
    if p is None:
        return {u"exists": False}
    info = {u"exists": True, u"readonly": bool(p.IsReadOnly)}
    s = _storage(p)
    info[u"storage"] = s
    try:
        if s == u"integer":
            info[u"value"] = p.AsInteger() if p.HasValue else None
        else:
            info[u"value"] = p.AsString()
    except Exception:
        info[u"value"] = None
    return info


def read_param_value(elem, name, storage):
    try:
        p = elem.LookupParameter(name)
        if storage == u"integer":
            return p.AsInteger()
        return p.AsString()
    except Exception:
        return None


# ============================================================
# Tags
# ============================================================

def tag_choices(doc):
    ints = {}
    for n in core.TAG_HOSTS:
        i = bic_int(n)
        if i is not None:
            ints[i] = n
    out = []
    try:
        symbols = list(FilteredElementCollector(doc).OfClass(FamilySymbol))
    except Exception:
        symbols = []
    for s in symbols:
        ci = cat_int(s)
        if ci not in ints:
            continue
        try:
            fam = s.FamilyName
        except Exception:
            fam = u""
        label = u"{0} : {1} : {2}".format(cat_label(s), fam, elem_name(s))
        out.append({u"label": label, u"id": s.Id, u"tag_cat": ints[ci]})
    out.sort(key=lambda d: d[u"label"].lower())
    return out


def view_can_tag(view, plans_only=False):
    if view is None or getattr(view, u"ViewType", None) is None:
        return False, u"Not a view"
    try:
        template = bool(view.IsTemplate)
    except Exception:
        template = False
    return core.tag_view_ok(view.ViewType, template, bool(getattr(view, u"IsLocked", False)),
                            plans_only)


def tags_in_view(doc, view):
    """{element id value: set of tag type id values} for every tag in the view."""
    out = {}
    try:
        tags = list(FilteredElementCollector(doc, view.Id).OfClass(IndependentTag))
    except Exception:
        tags = []
    for t in tags:
        try:
            tid = eid_value(t.GetTypeId())
        except Exception:
            continue
        ids = []
        try:
            ids = [eid_value(i) for i in t.GetTaggedLocalElementIds()]
        except Exception:
            try:
                ids = [eid_value(t.TaggedLocalElementId)]
            except Exception:
                ids = []
        for i in ids:
            out.setdefault(i, set()).add(tid)
    return out


def tag_point(elem, view):
    loc = None
    try:
        loc = elem.Location
    except Exception:
        pass
    try:
        if isinstance(loc, LocationCurve):
            return loc.Curve.Evaluate(0.5, True)
        if isinstance(loc, LocationPoint):
            return loc.Point
    except Exception:
        pass
    for v in (view, None):
        try:
            bb = elem.get_BoundingBox(v)
            if bb is not None:
                return (bb.Min + bb.Max) * 0.5
        except Exception:
            pass
    return None


# ============================================================
# The write
# ============================================================

class WarningSwallower(IFailuresPreprocessor):
    def __init__(self):
        self.messages = []

    def PreprocessFailures(self, accessor):
        try:
            for f in accessor.GetFailureMessages():
                if f.GetSeverity() == getattr(FailureSeverity, u"Warning"):
                    accessor.DeleteWarning(f)
                else:
                    try:
                        self.messages.append(f.GetDescriptionText())
                    except Exception:
                        pass
        except Exception:
            pass
        return getattr(FailureProcessingResult, u"Continue")


def _transaction(doc, name):
    t = Transaction(doc, name)
    sw = WarningSwallower()
    try:
        opts = t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(sw)
        t.SetFailureHandlingOptions(opts)
    except Exception:
        pass
    return t, sw


def _committed(status):
    return u"{0}".format(status) == u"Committed"


def checkout(doc, keys, idmap, log):
    """Borrow before writing. Returns (ok_keys, refused [(key, msg)])."""
    if not keys:
        return [], []
    try:
        shared = doc.IsWorkshared
    except Exception:
        shared = False
    if not shared:
        return list(keys), []
    ids = [idmap[k] for k in keys]
    held = set()
    try:
        for i in WorksharingUtils.CheckoutElements(doc, id_list(ids)):
            held.add(eid_value(i))
    except Exception:
        log.add(u"CheckoutElements failed: " + traceback.format_exc())
    me = u""
    try:
        me = doc.Application.Username or u""
    except Exception:
        pass
    ok = []
    refused = []
    for k in keys:
        if k in held:
            ok.append(k)
            continue
        owner = u""
        try:
            owner = WorksharingUtils.GetWorksharingTooltipInfo(doc, idmap[k]).Owner or u""
        except Exception:
            pass
        if not owner or owner == me:
            ok.append(k)
        else:
            refused.append((k, u"Borrowed by {0}".format(owner)))
    log.add(u"checkout: {0} ok, {1} refused".format(len(ok), len(refused)))
    return ok, refused


def _write_one(doc, elem, name, value):
    p = elem.LookupParameter(name)
    if p is None:
        return u"Parameter not on this element"
    if p.IsReadOnly:
        return u"Parameter is read-only here"
    if not p.Set(value):
        return u"Revit refused the value"
    return None


def apply_job(uiapp, job, log):
    """job: dict(param, storage, writes [(key, value)], same [key],
    idmap, tag dict(on, id, tag_cat) or None).
    Returns dict(written, same, tagged, tag_skipped, errors [(key, msg)])."""
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    name = job[u"param"]
    idmap = job[u"idmap"]
    res = {u"written": 0, u"same": len(job[u"same"]), u"tagged": 0,
           u"tag_skipped": 0, u"tag_views": 0, u"errors": []}
    errors = res[u"errors"]

    write_keys = [k for (k, v) in job[u"writes"]]
    values = dict(job[u"writes"])
    ok_keys, refused = checkout(doc, write_keys, idmap, log)
    errors.extend(refused)

    done = []
    tg = TransactionGroup(doc, u"RevoBIM Number Sequencer")
    tg.Start()
    try:
        # ---- numbers: one transaction, a sub-transaction per element
        if ok_keys:
            t, sw = _transaction(doc, u"Number sequence")
            t.Start()
            failed = []
            for k in ok_keys:
                elem = doc.GetElement(idmap[k])
                st = SubTransaction(doc)
                st.Start()
                try:
                    msg = _write_one(doc, elem, name, values[k])
                except Exception as ex:
                    msg = u"{0}".format(ex)
                if msg:
                    st.RollBack()
                    failed.append((k, msg))
                else:
                    st.Commit()
                    done.append(k)
            status = t.Commit()
            log.add(u"numbers transaction: {0} ({1} set, {2} refused)".format(
                status, len(done), len(failed)))
            if not _committed(status):
                # fall back to one transaction per element
                log.add(u"falling back per element: " + u"; ".join(sw.messages))
                done = []
                failed = []
                for k in ok_keys:
                    t1, sw1 = _transaction(doc, u"Number sequence")
                    t1.Start()
                    try:
                        msg = _write_one(doc, doc.GetElement(idmap[k]), name, values[k])
                    except Exception as ex:
                        msg = u"{0}".format(ex)
                    if msg:
                        t1.RollBack()
                        failed.append((k, msg))
                        continue
                    if _committed(t1.Commit()):
                        done.append(k)
                    else:
                        failed.append((k, u"; ".join(sw1.messages) or u"Revit rolled it back"))
            errors.extend(failed)

        # ---- tags
        tag = job.get(u"tag")
        if tag and tag.get(u"on") and tag.get(u"id") is not None:
            tag_keys = done + list(job[u"same"])
            _tag(doc, tag, tag_keys, idmap, res, log)

        tg.Assimilate()
    except Exception:
        log.add(u"apply failed: " + traceback.format_exc())
        try:
            tg.RollBack()
        except Exception:
            pass
        errors.append((None, u"Apply failed and was rolled back - see debug"))
        done = []

    # ---- read back after the group has closed
    storage = job.get(u"storage")
    for k in done:
        got = read_param_value(doc.GetElement(idmap[k]), name, storage)
        if core.value_matches(values[k], got):
            res[u"written"] += 1
        else:
            errors.append((k, u"Reads back {0!r}".format(got)))
    log.add(u"result: written {0}, unchanged {1}, tagged {2}, tag skipped {3}, errors {4}".format(
        res[u"written"], res[u"same"], res[u"tagged"], res[u"tag_skipped"], len(errors)))
    return res


def _tag(doc, tag, keys, idmap, res, log):
    """Tag the numbered elements. With views ticked in the Tag in views list,
    each ticked view gets tags on the numbered elements it shows; otherwise
    the active view does."""
    ticked = tag.get(u"views") or []
    if ticked and tag.get(u"views_doc") not in (None, doc_key(doc)):
        res[u"errors"].append((None, u"Tags not placed: the view list belongs to another document - "
                                     u"press All views to read this one's"))
        return
    if ticked:
        views = primary_views(doc, ticked)
    else:
        views = [doc.ActiveView]
        ok, why = view_can_tag(views[0], bool(tag.get(u"plans_only")))
        if not ok:
            res[u"errors"].append((None, u"Tags not placed: " + why))
            return
    res[u"tag_views"] = 0
    probe = visibility_probe(doc, [idmap[k] for k in keys if k in idmap]) if ticked else None
    for view in views:
        if ticked:
            # a ticked view may be a plan, a section or a locked 3D view
            ok, why = view_can_tag(view, False)
            if not ok:
                res[u"errors"].append((None, u"{0}: {1}".format(elem_name(view), why)))
                continue
            shown = visible_in_view(doc, view, None, probe=probe)
            here = [k for k in keys if k in shown]
        else:
            here = list(keys)
        if not here:
            continue
        n = _tag_view(doc, view, tag, here, idmap, res, log)
        if n:
            res[u"tag_views"] += 1


def _tag_view(doc, view, tag, keys, idmap, res, log):
    """Tag the numbered elements the view shows. Each element gets the tag
    chosen for its category (tag["by_host"]: the chosen tag where it can go,
    else one made for the category); untagged only leaves anything already
    tagged in this view alone, otherwise only the same tag is not repeated."""
    marks = tags_in_view(doc, view)
    by_host = tag.get(u"by_host") or {}
    untagged_only = tag.get(u"untagged_only", True)
    t, sw = _transaction(doc, u"Tag sequence")
    t.Start()
    used = [tag[u"id"]] + [v[u"id"] for v in by_host.values() if v is not None]
    for tid in used:
        try:
            sym = doc.GetElement(tid)
            if sym is not None and not sym.IsActive:
                sym.Activate()
        except Exception:
            pass
    placed = []
    orient = getattr(TagOrientation, u"Horizontal")
    for k in keys:
        elem = doc.GetElement(idmap[k])
        if elem is None:
            continue
        host = host_cat_name(elem)
        use = by_host.get(host) if host in by_host else (
            tag if core.tag_can_host(tag[u"tag_cat"], host) else None)
        if use is None:
            res[u"tag_skipped"] += 1
            res[u"tag_no_tag"] = res.get(u"tag_no_tag", 0) + 1
            continue
        if core.skip_tagging(marks.get(eid_value(idmap[k]), set()), eid_value(use[u"id"]), untagged_only):
            res[u"tag_skipped"] += 1
            res[u"tag_already"] = res.get(u"tag_already", 0) + 1
            continue
        pt = tag_point(elem, view)
        if pt is None:
            res[u"errors"].append((k, u"No point to place the tag"))
            continue
        st = SubTransaction(doc)
        st.Start()
        try:
            IndependentTag.Create(doc, use[u"id"], view.Id, Reference(elem),
                                  False, orient, pt)
            st.Commit()
            placed.append(k)
        except Exception as ex:
            st.RollBack()
            res[u"errors"].append((k, u"Tag refused in {0}: {1}".format(elem_name(view), ex)))
    status = t.Commit()
    log.add(u"tag {0}: {1} placed, {2}".format(elem_name(view), len(placed), status))
    if _committed(status):
        res[u"tagged"] += len(placed)
        return len(placed)
    if placed:
        res[u"errors"].append((None, u"Tags rolled back in {0}: {1}".format(
            elem_name(view), u"; ".join(sw.messages) or u"Revit refused")))
    return 0


# ============================================================
# Floor plans to tag in
# ============================================================

def _param_text(elem, name):
    if not name:
        return u""
    try:
        p = elem.LookupParameter(name)
    except Exception:
        p = None
    if p is None:
        return u""
    try:
        return p.AsValueString() or p.AsString() or u""
    except Exception:
        return u""


def floor_plans(doc):
    """Every floor plan (no templates), sorted by name."""
    return [v for v in tag_views(doc) if u"{0}".format(v.ViewType) == u"FloorPlan"]


def tag_views(doc):
    """Every view Tag in views offers - floor plans, sections and 3D views,
    no templates - sorted by name."""
    out = []
    try:
        items = list(FilteredElementCollector(doc).OfClass(View))
    except Exception:
        items = []
    for v in items:
        try:
            if v.IsTemplate or u"{0}".format(v.ViewType) not in core.TAG_VIEW_KINDS:
                continue
        except Exception:
            continue
        out.append(v)
    out.sort(key=lambda v: core.natural_key(elem_name(v)))
    return out


def view_param_names(views):
    """Parameter names carried by floor plans (sampled), for the group columns."""
    names = set()
    for v in views[:40]:
        try:
            for p in v.Parameters:
                try:
                    names.add(p.Definition.Name)
                except Exception:
                    pass
        except Exception:
            pass
    return sorted(names, key=lambda n: n.lower())


def view_table(doc, g1, g2):
    """Rows for the Tag in views list, and the parameter names to group by."""
    views = tag_views(doc)
    rows = []
    for v in views:
        try:
            level = v.GenLevel.Name if getattr(v, u"GenLevel", None) is not None else u""
        except Exception:
            level = u""
        kind = core.TAG_VIEW_KINDS.get(u"{0}".format(v.ViewType), u"")
        locked = bool(getattr(v, u"IsLocked", True)) if kind == u"3D" else True
        rows.append({u"id": eid_value(v.Id), u"eid": v.Id, u"uid": getattr(v, u"UniqueId", u""),
                     u"name": elem_name(v), u"level": level, u"kind": kind, u"locked": locked,
                     u"kind_text": core.kind_text(kind, locked),
                     u"g1": _param_text(v, g1), u"g2": _param_text(v, g2)})
    return rows, view_param_names(views)


def sheet_table(doc, view_values):
    """Every sheet (no placeholders) with the views placed on it that Tag in
    views lists (view_values), and how many views it holds in all."""
    want = set(view_values)
    out = []
    try:
        sheets = list(FilteredElementCollector(doc).OfClass(ViewSheet))
    except Exception:
        sheets = []
    for sh in sheets:
        try:
            if sh.IsTemplate or getattr(sh, u"IsPlaceholder", False):
                continue
        except Exception:
            continue
        views = []
        placed = 0
        try:
            for vid in sh.GetAllPlacedViews():
                placed += 1
                v = eid_value(vid)
                if v in want:
                    views.append(v)
        except Exception:
            pass
        out.append({u"uid": getattr(sh, u"UniqueId", u""), u"eid": sh.Id,
                    u"number": u"{0}".format(sh.SheetNumber or u""),
                    u"name": elem_name(sh), u"views": views, u"placed": placed})
    return out


def primary_views(doc, view_ids):
    """The views to tag: anything no longer a view is dropped, and a dependent
    view becomes its parent (dependents show the parent's tags), once each."""
    out = []
    seen = set()
    for vid in view_ids:
        v = doc.GetElement(vid)
        if v is None or not isinstance(v, View):
            continue
        try:
            pid = v.GetPrimaryViewId()
            if pid is not None and eid_value(pid) > 0:
                parent = doc.GetElement(pid)
                if parent is not None:
                    v = parent
        except Exception:
            pass
        k = eid_value(v.Id)
        if k not in seen:
            seen.add(k)
            out.append(v)
    return out


def visibility_probe(doc, eids):
    """Worked out once for many views: the wanted ids, a collector filter on
    just their categories, and their combined bounding box. eids are
    ElementIds held from the read - never rebuilt from integers (the
    constructor changed in Revit 2026)."""
    want = set([eid_value(i) for i in eids])
    ints = set()
    lo = None
    hi = None
    for i in eids:
        e = doc.GetElement(i)
        if e is None:
            continue
        ints.add(cat_int(e))
        try:
            bb = e.get_BoundingBox(None)
        except Exception:
            bb = None
        if bb is not None:
            mn = (bb.Min.X, bb.Min.Y, bb.Min.Z)
            mx = (bb.Max.X, bb.Max.Y, bb.Max.Z)
            lo = mn if lo is None else tuple([min(a, b) for a, b in zip(lo, mn)])
            hi = mx if hi is None else tuple([max(a, b) for a, b in zip(hi, mx)])
    cats = List[BuiltInCategory]()
    for name in known_cats():
        if bic_int(name) in ints:
            cats.Add(getattr(BuiltInCategory, name))
    return {u"want": want, u"cats": cats, u"box": (lo, hi) if lo is not None else None}


def _box_meets_crop(box, crop):
    inv, mn, mx, use_z = crop
    lo, hi = box
    corners = []
    for x in (lo[0], hi[0]):
        for y in (lo[1], hi[1]):
            for z in (lo[2], hi[2]):
                p = inv.OfPoint(XYZ(x, y, z))
                corners.append((p.X, p.Y, p.Z))
    return core.box_in_crop(corners, (mn.X, mn.Y, mn.Z), (mx.X, mx.Y, mx.Z), use_z, 0.01)


def visible_in_view(doc, view, eids, first_only=False, probe=None):
    """Which of these elements the view shows - its own visibility settings,
    and inside its crop region. One collector per view, on just the wanted
    elements' categories; a view whose crop misses them all is skipped."""
    probe = probe or visibility_probe(doc, eids)
    want = probe[u"want"]
    if not want or probe[u"cats"].Count == 0:
        return set()
    crop = _crop(view)
    if crop is not None and probe[u"box"] is not None and not _box_meets_crop(probe[u"box"], crop):
        return set()
    try:
        ids = (FilteredElementCollector(doc, view.Id).WherePasses(ElementMulticategoryFilter(probe[u"cats"]))
               .WhereElementIsNotElementType().ToElementIds())
    except Exception:
        return set()
    found = set()
    for i in ids:
        k = eid_value(i)
        if k not in want or k in found:
            continue
        if crop is not None and not _inside_crop(doc.GetElement(i), crop):
            continue
        found.add(k)
        if first_only:
            break
    return found


def views_showing(doc, view_ids, eids):
    """Id values of the views (from view_ids) that show any of the elements -
    stopping at the first element found in each view."""
    probe = visibility_probe(doc, eids)
    out = set()
    for vid in view_ids:
        view = doc.GetElement(vid)
        if view is None or not isinstance(view, View):
            continue
        if visible_in_view(doc, view, eids, first_only=True, probe=probe):
            out.add(eid_value(vid))
    return out


# ============================================================
# Picking and showing
# ============================================================

class _DuctFilter(ISelectionFilter):
    def __init__(self, ints):
        self.ints = ints

    def AllowElement(self, elem):
        try:
            return cat_int(elem) in self.ints
        except Exception:
            return False

    def AllowReference(self, ref, point):
        return False


def pick_duct_element(uidoc, prompt):
    """None when the user pressed Escape."""
    return pick_element(uidoc, walk_ints(), prompt)


def pick_element(uidoc, ints, prompt):
    try:
        ref = uidoc.Selection.PickObject(getattr(ObjectType, u"Element"),
                                         _DuctFilter(ints), prompt)
    except Exception:
        return None
    if ref is None:
        return None
    return uidoc.Document.GetElement(ref.ElementId)


def pick_many(uidoc, ints, prompt):
    """Element id values picked (window or one by one, Finish to end).
    None when the user pressed Escape."""
    try:
        refs = uidoc.Selection.PickObjects(getattr(ObjectType, u"Element"),
                                           _DuctFilter(ints), prompt)
    except Exception:
        return None
    out = []
    for r in refs or []:
        try:
            out.append(eid_value(r.ElementId))
        except Exception:
            pass
    return out


def select_and_show(uidoc, ids, zoom=True):
    ids = [i for i in ids if i is not None]
    try:
        uidoc.Selection.SetElementIds(id_list(ids))
    except Exception:
        pass
    if not ids or not zoom:
        return
    try:
        uidoc.ShowElements(id_list(ids))
    except Exception:
        pass


# ============================================================
# System selector: every duct or pipe system in the active view
# ============================================================

def kind_ints(kind, part):
    return set([i for i in [bic_int(n) for n in core.KINDS[kind][part]] if i is not None])


def _crop(view):
    """(inverse transform, min, max, use z) of the crop region or 3D section
    box when one is on, else None."""
    try:
        if getattr(view, u"IsSectionBoxActive", False):
            box = view.GetSectionBox()
            return box.Transform.Inverse, box.Min, box.Max, True
        if view.CropBoxActive:
            box = view.CropBox
            return box.Transform.Inverse, box.Min, box.Max, False
    except Exception:
        pass
    return None


def _inside_crop(elem, crop):
    inv, mn, mx, use_z = crop
    try:
        bb = elem.get_BoundingBox(None)
    except Exception:
        bb = None
    if bb is None:
        return True
    corners = []
    for x in (bb.Min.X, bb.Max.X):
        for y in (bb.Min.Y, bb.Max.Y):
            for z in (bb.Min.Z, bb.Max.Z):
                p = inv.OfPoint(XYZ(x, y, z))
                corners.append((p.X, p.Y, p.Z))
    return core.box_in_crop(corners, (mn.X, mn.Y, mn.Z), (mx.X, mx.Y, mx.Z), use_z, 0.01)


def elements_in_view(doc, view, names, log=None):
    """Elements of these categories visible in the view, no types, kept to
    the crop region / section box - Revit's view collector can hand back
    elements beyond the crop."""
    out = []
    seen = set()
    crop = _crop(view)
    dropped = 0
    for name in names:
        bic = getattr(BuiltInCategory, name, None)
        if bic is None:
            continue
        try:
            col = FilteredElementCollector(doc, view.Id).OfCategory(bic).WhereElementIsNotElementType()
            items = list(col)
        except Exception:
            items = []
        for e in items:
            k = eid_value(e.Id)
            if k in seen:
                continue
            seen.add(k)
            if crop is not None and not _inside_crop(e, crop):
                dropped += 1
                continue
            out.append(e)
    if log is not None:
        log.add(u"view collector: {0} elements, {1} outside the {2} left out".format(
            len(out) + dropped, dropped,
            u"crop region" if crop is not None and not crop[3] else
            u"section box" if crop is not None else u"(no crop on)"))
    return out


def elem_system(elem):
    """The MEPSystem an element is on, or None (fabrication parts often)."""
    try:
        sysel = elem.MEPSystem
        if sysel is not None:
            return sysel
    except Exception:
        pass
    for c in iter_connectors(elem):
        try:
            sysel = c.MEPSystem
            if sysel is not None:
                return sysel
        except Exception:
            pass
    return None


def fab_service(elem):
    for attr in (u"ServiceName",):
        try:
            v = getattr(elem, attr)
            if v:
                return u"{0}".format(v)
        except Exception:
            pass
    return _bip_text(elem, u"FABRICATION_SERVICE_PARAM")


def system_info(doc, sysel):
    """System references: name, system type, abbreviation, classification."""
    t = None
    try:
        t = doc.GetElement(sysel.GetTypeId())
    except Exception:
        t = None
    abbr = u""
    for holder in (t, sysel):
        if holder is not None and not abbr:
            abbr = _bip_text(holder, u"RBS_SYSTEM_ABBREVIATION_PARAM")
    return {u"name": elem_name(sysel) or _bip_text(sysel, u"RBS_SYSTEM_NAME_PARAM"),
            u"type": elem_name(t) if t is not None else u"",
            u"abbr": abbr,
            u"cls": _bip_text(sysel, u"RBS_SYSTEM_CLASSIFICATION_PARAM")}


def _type_param_name(kind):
    return u"RBS_DUCT_SYSTEM_TYPE_PARAM" if kind == u"duct" else u"RBS_PIPING_SYSTEM_TYPE_PARAM"


def selector_from_elems(doc, elems, kind, log):
    """Group the elements into systems. Accessories are walked through but
    never numbered or selected; terminals / fixtures joined to a system are
    kept for isolating only; equipment is never touched."""
    data = read_network(doc, elems, log)
    storages, per_elem = param_map(elems)
    data[u"storages"] = storages
    data[u"per_elem"] = per_elem
    through = kind_ints(kind, u"through")
    ends = kind_ints(kind, u"ends")
    passthrough = set()
    labels = {}
    info = {}
    fab = {}
    for e in elems:
        k = eid_value(e.Id)
        if cat_int(e) in through:
            passthrough.add(k)
        if isinstance(e, FabricationPart):
            fab[k] = fab_service(e)
        sysel = elem_system(e)
        if sysel is not None:
            sk = u"id:{0}".format(eid_value(sysel.Id))
            if sk not in info:
                info[sk] = system_info(doc, sysel)
            labels[k] = sk
            continue
        nm = _bip_text(e, u"RBS_SYSTEM_NAME_PARAM")
        if nm:
            sk = u"name:" + nm
            if sk not in info:
                info[sk] = {u"name": nm, u"type": _bip_text(e, _type_param_name(kind)) or fab.get(k, u""),
                            u"abbr": u"", u"cls": u""}
            labels[k] = sk
        else:
            labels[k] = None
    assign = core.assign_systems(data[u"nodes"], labels)
    groups = {}
    for k in sorted(assign):
        groups.setdefault(assign[k], []).append(k)
    extras = {}
    for e in elems:
        k = eid_value(e.Id)
        for c in iter_connectors(e):
            for r in conn_refs(c):
                try:
                    o = r.Owner
                except Exception:
                    continue
                if o is not None and cat_int(o) in ends:
                    extras.setdefault(assign.get(k), {})[eid_value(o.Id)] = o.Id
    systems = []
    for sk, keys in groups.items():
        num = [k for k in keys if k not in passthrough]
        if not num:
            continue  # nothing to number: accessories on their own
        inf = info.get(sk)
        if inf is None:
            svc = u""
            for k in keys:
                if fab.get(k):
                    svc = fab[k]
                    break
            inf = {u"name": u"No system - " + svc if svc else u"No system", u"type": svc,
                   u"abbr": u"", u"cls": u""}
        systems.append({u"key": sk, u"name": inf[u"name"] or sk, u"type": inf[u"type"],
                        u"abbr": inf[u"abbr"], u"cls": inf[u"cls"], u"keys": keys,
                        u"num": num, u"extras": list(extras.get(sk, {}).values()),
                        u"on": True, u"start": None, u"colour": None})
    systems.sort(key=lambda sd: (sd[u"key"].startswith(u"piece:"), core.natural_key(sd[u"name"]), sd[u"key"]))
    keep = set(k for sd in systems for k in sd[u"num"])
    data[u"rows"] = [r for r in data[u"rows"] if r[0] in keep]
    data[u"passthrough"] = passthrough
    data[u"systems"] = systems
    log.add(u"selector {0}: {1} elements, {2} accessories walked through, {3} systems".format(
        kind, len(elems), len(passthrough), len(systems)))
    named = len([k for k in labels if labels[k] and labels[k].startswith(u"id:")])
    by_name = len([k for k in labels if labels[k] and labels[k].startswith(u"name:")])
    log.add(u"  labels: {0} on a Revit system, {1} by System Name only, {2} with neither "
            u"({3} fabrication parts)".format(named, by_name, len(labels) - named - by_name, len(fab)))
    g = core.group_summary(systems)
    log.add(u"  rows: {0} Revit systems, {1} named only, {2} loose pieces ({3} of one part)".format(*g))
    for sd in systems[:60]:
        log.add(u"  {0} | {1} | {2} elements".format(sd[u"key"], sd[u"name"], len(sd[u"keys"])))
    if len(systems) > 60:
        log.add(u"  ... {0} more".format(len(systems) - 60))
    return data


def read_selector(doc, view, kind, log):
    names = core.KINDS[kind][u"walk"] + core.KINDS[kind][u"through"]
    elems = elements_in_view(doc, view, names, log)
    data = selector_from_elems(doc, elems, kind, log)
    data[u"view_id"] = view.Id
    data[u"view_name"] = elem_name(view)
    data[u"view_type"] = u"{0}".format(view.ViewType)
    return data


def tags_on(doc, view, id_values):
    """Tags in the view that tag any of these elements."""
    want = set(id_values)
    out = []
    try:
        tags = list(FilteredElementCollector(doc, view.Id).OfClass(IndependentTag))
    except Exception:
        tags = []
    for t in tags:
        hosts = []
        try:
            hosts = [eid_value(i) for i in t.GetTaggedLocalElementIds()]
        except Exception:
            try:
                hosts = [eid_value(t.TaggedLocalElementId)]
            except Exception:
                hosts = []
        if any([h in want for h in hosts]):
            out.append(t.Id)
    return out


def _section_box_ids(doc, view):
    if not getattr(view, u"IsSectionBoxActive", False):
        return []
    try:
        bic = getattr(BuiltInCategory, u"OST_SectionBox")
        return list(view.GetDependentElements(ElementCategoryFilter(bic)))
    except Exception:
        return []


def reset_isolate(uidoc, log):
    ok = reset_isolate_view(uidoc.Document, uidoc.Document.ActiveView.Id, log)
    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass
    return ok


def reset_isolate_view(doc, view_id, log):
    """Turn off temporary hide / isolate in a view, active or not."""
    view = doc.GetElement(view_id)
    if view is None or getattr(view, u"DisableTemporaryViewMode", None) is None:
        return False
    t, sw = _transaction(doc, u"Reset temporary isolate")
    t.Start()
    for name in (u"TemporaryHideIsolate", u"RevealHiddenElements"):
        mode = getattr(TemporaryViewMode, name, None)
        if mode is None:
            continue
        try:
            view.DisableTemporaryViewMode(mode)
        except Exception:
            pass
    status = t.Commit()
    log.add(u"reset isolate in view {0}: {1}".format(eid_value(view_id), status))
    return _committed(status)


def hide_temporary(uidoc, ids, log):
    """Temporary hide elements in the active view (outside an isolate)."""
    doc = uidoc.Document
    view = doc.ActiveView
    t, sw = _transaction(doc, u"Hide removed elements")
    t.Start()
    try:
        view.HideElementsTemporary(id_list(ids))
        status = t.Commit()
    except Exception:
        t.RollBack()
        raise
    log.add(u"temporary hide {0}: {1}".format(len(ids), status))
    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass
    return _committed(status)


def open_documents(uiapp):
    """(document key, document) for every open project that can be changed."""
    out = []
    try:
        docs = list(uiapp.Application.Documents)
    except Exception:
        docs = []
    for d in docs:
        try:
            if d.IsLinked or d.IsFamilyDocument:
                continue
        except Exception:
            continue
        out.append((doc_key(d), d))
    return out


def selected_ids(uidoc):
    try:
        return list(uidoc.Selection.GetElementIds())
    except Exception:
        return []


def isolate_systems(uidoc, ids, log, view=None):
    """Temporary isolate the systems plus every tag on them, in the active
    view or the view given (Isolate in 3D isolates a view before opening it).
    The old isolate is reset in its own committed transaction first -
    resetting in the same transaction let a leftover isolate show through."""
    doc = uidoc.Document
    if view is None:
        view = doc.ActiveView
    values = [eid_value(i) for i in ids]
    keep = list(ids)
    tg = TransactionGroup(doc, u"RevoBIM Number Sequencer isolate")
    tg.Start()
    t = None
    t2 = None
    try:
        t, sw = _transaction(doc, u"Reset temporary isolate")
        t.Start()
        for name in (u"TemporaryHideIsolate", u"RevealHiddenElements"):
            mode = getattr(TemporaryViewMode, name, None)
            if mode is not None:
                try:
                    view.DisableTemporaryViewMode(mode)
                except Exception:
                    pass
        t.Commit()
        # gathered after the reset: a view collector skips what an isolate hides
        keep = list(ids) + tags_on(doc, view, values) + _section_box_ids(doc, view)
        t2, sw2 = _transaction(doc, u"Isolate systems")
        t2.Start()
        view.IsolateElementsTemporary(id_list(keep))
        status = t2.Commit()
        tg.Assimilate()
    except Exception:
        for open_t in (t2, t):
            try:
                if open_t is not None and open_t.HasStarted() and not open_t.HasEnded():
                    open_t.RollBack()
            except Exception:
                pass
        try:
            tg.RollBack()
        except Exception:
            pass
        raise
    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass
    log.add(u"isolate: {0} elements + tags, {1}".format(len(keep), status))
    return len(keep)


# ============================================================
# Isolate in 3D: the 3D view to use
# ============================================================

SECTION_BOX_MARGIN = 1.0   # feet (300 mm) round the systems


def fit_section_box(doc, view, ids, log, margin=SECTION_BOX_MARGIN):
    """A 3D view whose section box is on: move the box to the systems (their
    combined extent plus a margin). Returns the box it had before when it
    moved (so a reset can put it back), else None. A view with no section box
    is left as it is - the isolate already shows only them."""
    try:
        if not view.IsSectionBoxActive:
            return None
        old = view.GetSectionBox()
    except Exception:
        return None
    lo = None
    hi = None
    for i in ids:
        try:
            bb = doc.GetElement(i).get_BoundingBox(None)
        except Exception:
            bb = None
        if bb is None:
            continue
        a = (bb.Min.X, bb.Min.Y, bb.Min.Z)
        b = (bb.Max.X, bb.Max.Y, bb.Max.Z)
        lo = a if lo is None else tuple([min(lo[k], a[k]) for k in range(3)])
        hi = b if hi is None else tuple([max(hi[k], b[k]) for k in range(3)])
    if lo is None:
        return None
    box = BoundingBoxXYZ()
    box.Min = XYZ(lo[0] - margin, lo[1] - margin, lo[2] - margin)
    box.Max = XYZ(hi[0] + margin, hi[1] + margin, hi[2] + margin)
    t, sw = _transaction(doc, u"Fit section box to the systems")
    t.Start()
    try:
        view.SetSectionBox(box)
        status = t.Commit()
    except Exception:
        try:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        log.add(u"section box fit failed: " + traceback.format_exc())
        return None
    log.add(u"section box fitted to {0} elements: {1}".format(len(ids), status))
    return old if _committed(status) else None


def restore_section_box(doc, view_id, box, log):
    """Put a 3D view's section box back as it was before the tool fitted it."""
    view = doc.GetElement(view_id)
    if view is None or box is None:
        return False
    t, sw = _transaction(doc, u"Put the section box back")
    t.Start()
    try:
        view.SetSectionBox(box)
        status = t.Commit()
    except Exception:
        try:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        log.add(u"section box restore failed: " + traceback.format_exc())
        return False
    log.add(u"section box put back: {0}".format(status))
    return _committed(status)


def views_3d(doc):
    """Every 3D view Isolate in 3D can use - no templates - as
    (UniqueId, name), sorted by name."""
    out = []
    try:
        items = list(FilteredElementCollector(doc).OfClass(View3D))
    except Exception:
        items = []
    for v in items:
        try:
            if v.IsTemplate:
                continue
        except Exception:
            continue
        out.append((getattr(v, u"UniqueId", u""), elem_name(v)))
    out.sort(key=lambda r: core.natural_key(r[1]))
    return out


def _user_name(doc):
    try:
        return doc.Application.Username or u""
    except Exception:
        return u""


def default_3d(doc):
    """The view Revit's Default 3D View button opens: {3D - user} in a
    workshared model, {3D} otherwise, else any {3D...} view."""
    names = core.default_3d_names(_user_name(doc))
    found = {}
    try:
        items = list(FilteredElementCollector(doc).OfClass(View3D))
    except Exception:
        items = []
    for v in items:
        try:
            if v.IsTemplate:
                continue
        except Exception:
            continue
        found.setdefault(elem_name(v), v)
    pick = core.pick_default_3d(list(found), names)
    return found.get(pick) if pick is not None else None


def view_by_uid(doc, uid):
    if not uid:
        return None
    try:
        v = doc.GetElement(uid)
    except Exception:
        return None
    try:
        if v is None or v.IsTemplate or u"{0}".format(v.ViewType) != u"ThreeD":
            return None
    except Exception:
        return None
    return v


def create_default_3d(doc, log):
    """No 3D view to use: make an isometric one and name it like Revit's own."""
    family = getattr(ViewFamily, u"ThreeDimensional", None)
    vft = None
    for t_ in FilteredElementCollector(doc).OfClass(ViewFamilyType):
        try:
            if t_.ViewFamily == family:
                vft = t_
                break
        except Exception:
            pass
    if vft is None:
        raise Exception(u"No 3D view type in this model")
    t, sw = _transaction(doc, u"Create default 3D view")
    t.Start()
    try:
        view = View3D.CreateIsometric(doc, vft.Id)
        for name in core.default_3d_names(_user_name(doc)):
            try:
                view.Name = name
                break
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
    log.add(u"created 3D view {0}: {1}".format(elem_name(view), status))
    return view


def open_views(uidoc, view_ids, log):
    """Open each view or sheet in Revit, one after another (each becomes a
    tab; the last stays in front). Returns how many opened."""
    doc = uidoc.Document
    n = 0
    last = None
    for vid in view_ids:
        view = doc.GetElement(vid)
        if view is None:
            continue
        last = view
        try:
            uidoc.ActiveView = view
            n += 1
        except Exception:
            log.add(u"could not open {0}: {1}".format(elem_name(view), traceback.format_exc()))
    if n == 0 and last is not None:
        try:
            uidoc.RequestViewChange(last)
            n = 1
        except Exception:
            pass
    log.add(u"opened {0} of {1} views / sheets".format(n, len(view_ids)))
    return n


def zoom_view(uidoc, view_id):
    """Zoom the open window of a view to fit (after an isolate that is the systems)."""
    try:
        for uiv in uidoc.GetOpenUIViews():
            if eid_value(uiv.ViewId) == eid_value(view_id):
                uiv.ZoomToFit()
                return True
    except Exception:
        pass
    return False


# ============================================================
# Colour each system in the view, and put the view back afterwards
# ============================================================

def solid_fill_id(doc):
    try:
        for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
            try:
                if fp.GetFillPattern().IsSolidFill:
                    return fp.Id
            except Exception:
                pass
    except Exception:
        pass
    return None


def _call(obj, name, *args):
    fn = getattr(obj, name, None)
    if fn is None:
        return False
    try:
        fn(*args)
        return True
    except Exception:
        return False


def colour_settings(hex_text, solid_id, weight=None):
    r, g, b = core.hex_rgb(hex_text)
    col = RevitColor(r, g, b)
    ogs = OverrideGraphicSettings()
    for name in (u"SetProjectionLineColor", u"SetCutLineColor",
                 u"SetSurfaceForegroundPatternColor", u"SetCutForegroundPatternColor"):
        _call(ogs, name, col)
    if solid_id is not None:
        for name in (u"SetSurfaceForegroundPatternId", u"SetCutForegroundPatternId"):
            _call(ogs, name, solid_id)
        for name in (u"SetSurfaceForegroundPatternVisible", u"SetCutForegroundPatternVisible"):
            _call(ogs, name, True)
    if weight:
        for name in (u"SetProjectionLineWeight", u"SetCutLineWeight"):
            _call(ogs, name, int(weight))
    # the tool's mark (1% - not visible): a colouring left behind is found by it
    _call(ogs, u"SetSurfaceTransparency", core.COLOUR_MARK)
    return ogs


def _rgb(colour):
    try:
        if colour is None or not colour.IsValid:
            return None
        return (int(colour.Red), int(colour.Green), int(colour.Blue))
    except Exception:
        return None


def is_tool_colour(ogs):
    """Overrides this tool set (see core.is_tool_colouring)."""
    try:
        cols = [_rgb(getattr(ogs, n, None)) for n in (u"ProjectionLineColor", u"CutLineColor",
                                                      u"SurfaceForegroundPatternColor",
                                                      u"CutForegroundPatternColor")]
        return core.is_tool_colouring(cols, getattr(ogs, u"SurfaceTransparency", 0))
    except Exception:
        return False


def tool_coloured(view, ids):
    """The elements in ids that still carry the tool's colouring in this view -
    left behind by a session that closed without putting them back."""
    out = []
    for i in ids:
        try:
            if is_tool_colour(view.GetElementOverrides(i)):
                out.append(i)
        except Exception:
            pass
    return out


def clear_overrides(doc, view_id, ids, log):
    """Take the tool's colouring off these elements (no record of what was
    there before it, so they go back to no override)."""
    view = doc.GetElement(view_id)
    if view is None or not ids:
        return 0
    t, sw = _transaction(doc, u"Clear system colours")
    t.Start()
    count = 0
    for i in ids:
        try:
            if is_tool_colour(view.GetElementOverrides(i)):
                view.SetElementOverrides(i, OverrideGraphicSettings())
                count += 1
        except Exception:
            pass
    status = t.Commit()
    log.add(u"clear left-over colours: {0} elements, {1}".format(count, status))
    return count if _committed(status) else 0


def colour_systems(doc, view, groups, snapshot, log):
    """groups: [(hex colour, [ElementId], line weight or None)], later groups
    win (the start colour goes last). snapshot {id value: (ElementId,
    OverrideGraphicSettings)} records what each element looked like before the
    tool first touched it, so clearing puts the view back exactly."""
    try:
        if doc.IsWorkshared:
            WorksharingUtils.CheckoutElements(doc, id_list([view.Id]))
    except Exception:
        log.add(u"view checkout failed: " + traceback.format_exc())
    solid = solid_fill_id(doc)
    t, sw = _transaction(doc, u"Colour systems")
    t.Start()
    count = 0
    first_seen = {}
    for group in groups:
        hex_text, ids = group[0], group[1]
        ogs = colour_settings(hex_text, solid, group[2] if len(group) > 2 else None)
        for i in ids:
            k = eid_value(i)
            try:
                if k not in snapshot and k not in first_seen:
                    before = view.GetElementOverrides(i)
                    if is_tool_colour(before):
                        # left by an earlier session: clearing must take it off, not put it back
                        before = OverrideGraphicSettings()
                    first_seen[k] = (i, before)
                view.SetElementOverrides(i, ogs)
                count += 1
            except Exception:
                pass
    status = t.Commit()
    log.add(u"colour systems: {0} elements, {1}".format(count, status))
    if not _committed(status):
        # nothing changed: keep what an earlier colouring recorded
        raise Exception(u"Revit would not colour the view: " + (u"; ".join(sw.messages) or u"rolled back"))
    snapshot.update(first_seen)
    return count


def doc_key(doc):
    try:
        return u"{0}|{1}".format(doc.PathName or u"", doc.Title or u"")
    except Exception:
        return u""


def is_isolated(view):
    mode = getattr(TemporaryViewMode, u"TemporaryHideIsolate", None)
    try:
        return mode is not None and bool(view.IsInTemporaryViewMode(mode))
    except Exception:
        return False


def restore_overrides(doc, view_id, snapshot, log):
    """Put back every element override recorded in the snapshot. The caller
    makes sure doc is the document the snapshot was taken in."""
    if not snapshot:
        return 0
    view = doc.GetElement(view_id)
    if view is None or getattr(view, u"SetElementOverrides", None) is None:
        snapshot.clear()
        return 0
    t, sw = _transaction(doc, u"Clear system colours")
    t.Start()
    count = 0
    for k in list(snapshot):
        i, ogs = snapshot[k]
        try:
            view.SetElementOverrides(i, ogs)
            count += 1
        except Exception:
            pass
    status = t.Commit()
    log.add(u"clear colours: {0} elements, {1}".format(count, status))
    if _committed(status):
        snapshot.clear()
    return count
