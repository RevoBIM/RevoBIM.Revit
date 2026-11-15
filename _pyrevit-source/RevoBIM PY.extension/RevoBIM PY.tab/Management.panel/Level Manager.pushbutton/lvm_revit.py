# -*- coding: utf-8 -*-
"""Level Manager - every read of the model, and the adapter the assign
algorithm in lvm_core drives. Enum members are looked up at call time."""
import lvm_clr  # noqa: F401  (references first)
import time

from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    FilteredElementCollector, Level, ElementId, BuiltInParameter,
    BuiltInCategory, CategoryType, StorageType, LocationPoint, LocationCurve,
    XYZ, ElementTransformUtils, WorksharingUtils, MEPCurve, FamilyInstance,
    FabricationPart, Transaction, TransactionGroup, IFailuresPreprocessor,
    FailureProcessingResult, FailureSeverity, View, View3D, ViewSheet, Viewport,
    ViewFamilyType, ViewFamily, ElementCategoryFilter, BoundingBoxXYZ,
    TemporaryViewMode, Category, Element,
)

import lvm_core as core

to_text = core.to_text


# =========================================================================
# Small helpers
# =========================================================================

def eid_value(element_id):
    """ElementId to a number on every release (IntegerValue went in 2026)."""
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


def bip(name):
    return getattr(BuiltInParameter, name, None)


def bic(name):
    return getattr(BuiltInCategory, name, None)


def enum_is(value, type_obj, member):
    target = getattr(type_obj, member, None)
    if target is None:
        return False
    try:
        return value == target
    except Exception:
        return to_text(value) == member


def name_of(element):
    """Element.Name raises in IronPython on some classes - guard every read."""
    if element is None:
        return u""
    try:
        return to_text(element.Name)
    except Exception:
        pass
    try:
        p = element.get_Parameter(bip("SYMBOL_NAME_PARAM"))
        if p is not None:
            return to_text(p.AsString())
    except Exception:
        pass
    return u""


def param_for(element, route):
    if element is None or not route:
        return None
    try:
        if route.startswith("name:"):
            return element.LookupParameter(route[5:])
        member = bip(route)
        if member is None:
            return None
        return element.get_Parameter(member)
    except Exception:
        return None


def is_elementid_param(p):
    try:
        return enum_is(p.StorageType, StorageType, "ElementId")
    except Exception:
        return False


def is_double_param(p):
    try:
        return enum_is(p.StorageType, StorageType, "Double")
    except Exception:
        return False


def doc_key(doc):
    try:
        path = to_text(doc.PathName)
        if path:
            return path
    except Exception:
        pass
    try:
        return to_text(doc.Title)
    except Exception:
        return u""


def canvas_is_dark(uiapp):
    """True / False from Revit's canvas theme, None if unreadable.
    UIThemeManager only exists from 2024, so reach it by getattr."""
    try:
        import Autodesk.Revit.UI as rui
        mgr = getattr(rui, "UIThemeManager", None)
        if mgr is not None:
            theme = mgr.CurrentCanvasTheme
            if theme is not None:
                result = core.canvas_theme_is_dark(theme)
                if result is not None:
                    return result
    except Exception:
        pass
    try:
        colour = uiapp.Application.BackgroundColor
        return core.colour_is_dark(colour.Red, colour.Green, colour.Blue)
    except Exception:
        return None


# =========================================================================
# Positions
# =========================================================================

def snapshot(element):
    """Where an element is: its location then its bounding box, as floats.
    The first three numbers are the anchor point used for the vertical shift."""
    if element is None:
        return None
    vals = []
    try:
        loc = element.Location
        if isinstance(loc, LocationPoint):
            p = loc.Point
            vals.extend([p.X, p.Y, p.Z])
        elif isinstance(loc, LocationCurve):
            c = loc.Curve
            a = c.GetEndPoint(0)
            b = c.GetEndPoint(1)
            vals.extend([a.X, a.Y, a.Z, b.X, b.Y, b.Z])
    except Exception:
        vals = []
    try:
        bb = element.get_BoundingBox(None)
        if bb is not None:
            if not vals:
                vals.extend([bb.Min.X, bb.Min.Y, bb.Min.Z])
            vals.extend([bb.Min.X, bb.Min.Y, bb.Min.Z, bb.Max.X, bb.Max.Y, bb.Max.Z])
    except Exception:
        pass
    return tuple(vals) if vals else None


def anchor_z(element):
    """The elevation shown in the table: a point family's insertion point,
    an MEP run's centreline at mid length, otherwise the bottom of its box."""
    try:
        loc = element.Location
        if isinstance(loc, LocationPoint):
            return loc.Point.Z
        if isinstance(element, MEPCurve) and isinstance(loc, LocationCurve):
            return loc.Curve.Evaluate(0.5, True).Z
    except Exception:
        pass
    try:
        bb = element.get_BoundingBox(None)
        if bb is not None:
            return bb.Min.Z
    except Exception:
        pass
    try:
        loc = element.Location
        if isinstance(loc, LocationCurve):
            return loc.Curve.Evaluate(0.5, True).Z
    except Exception:
        pass
    return None


def connector_manager(element):
    try:
        cm = element.ConnectorManager
        if cm is not None:
            return cm
    except Exception:
        pass
    try:
        mep = element.MEPModel
        if mep is not None:
            return mep.ConnectorManager
    except Exception:
        pass
    return None


def neighbour_ids(element):
    """ElementIds of the pipes, ducts, trays and fittings joined to this one."""
    out = []
    cm = connector_manager(element)
    if cm is None:
        return out
    try:
        own = eid_value(element.Id)
        for c in cm.Connectors:
            try:
                if not c.IsConnected:
                    continue
                for r in c.AllRefs:
                    owner = r.Owner
                    if owner is None or eid_value(owner.Id) == own:
                        continue
                    if isinstance(owner, MEPCurve) or isinstance(owner, FamilyInstance) \
                            or isinstance(owner, FabricationPart):
                        out.append(owner.Id)
            except Exception:
                continue
    except Exception:
        pass
    return out


# =========================================================================
# Reading the project
# =========================================================================

def find_route(element, cat_id, hints):
    """(route, level id, note). The route is the first level parameter that
    holds a level and can be written; hints remember, per category, which
    route hit last so most elements need one lookup."""
    order = list(range(len(core.ROUTES)))
    hint = hints.get(cat_id)
    if hint is not None:
        order.remove(hint)
        order.insert(0, hint)
    first_ro = None
    for idx in order:
        route = core.ROUTES[idx][0]
        p = param_for(element, route)
        if p is None or not is_elementid_param(p):
            continue
        try:
            lid = eid_value(p.AsElementId())
        except Exception:
            continue
        if lid <= 0:
            continue
        try:
            read_only = p.IsReadOnly
        except Exception:
            read_only = True
        if read_only:
            if first_ro is None:
                first_ro = (route, lid)
            continue
        hints[cat_id] = idx
        return route, lid, u""
    if first_ro is not None:
        return None, first_ro[1], u"Level is read-only - set by its host or by Revit"
    try:
        lid = eid_value(element.LevelId)
    except Exception:
        lid = 0
    return None, lid, u"Level is not editable"


def read_levels(doc, ids):
    levels = []
    for lv in FilteredElementCollector(doc).OfClass(Level):
        try:
            proj = float(lv.ProjectElevation)
        except Exception:
            continue
        disp = proj
        try:
            p = lv.get_Parameter(bip("LEVEL_ELEV"))
            if p is not None:
                disp = float(p.AsDouble())
        except Exception:
            pass
        lid = eid_value(lv.Id)
        ids[lid] = lv.Id
        levels.append({"id": lid, "name": name_of(lv), "proj": proj, "disp": disp})
    return levels


def display_shift(levels):
    """Elevations are shown on the same basis Revit shows the levels on
    (project or survey). Take the shift most levels share."""
    counts = {}
    for lv in levels:
        key = round(lv["disp"] - lv["proj"], 6)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return 0.0
    return max(counts.items(), key=lambda kv: kv[1])[0]


def read_project(doc, param_names=None, log=None):
    """Every level, and every model element associated with one."""
    log = log or (lambda msg: None)
    started = time.time()
    ids = {}
    levels = read_levels(doc, ids)
    level_ids = set([lv["id"] for lv in levels])
    shift = display_shift(levels)

    excluded = set()
    for name in core.EXCLUDED_CATEGORIES:
        member = bic(name)
        if member is None:
            continue
        try:
            excluded.add(int(member))
        except Exception:
            try:
                excluded.add(int(getattr(member, "value__")))
            except Exception:
                pass
    model_type = getattr(CategoryType, "Model", None)
    workshared = False
    try:
        workshared = bool(doc.IsWorkshared)
    except Exception:
        pass
    ws_table = None
    if workshared:
        try:
            ws_table = doc.GetWorksetTable()
        except Exception:
            ws_table = None

    hints = {}
    type_cache = {}
    ws_cache = {}
    elements = []
    skipped = 0
    for e in FilteredElementCollector(doc).WhereElementIsNotElementType():
        try:
            cat = e.Category
            if cat is None:
                continue
            cid = eid_value(cat.Id)
            if cid in excluded:
                continue
            if model_type is not None and cat.CategoryType != model_type:
                continue
            if e.ViewSpecific or isinstance(e, Level):
                continue
            route, lid, note = find_route(e, cid, hints)
            if lid not in level_ids:
                continue
            eid = eid_value(e.Id)
            ids[eid] = e.Id
            assignable = route is not None
            try:
                gid = eid_value(e.GroupId)
            except Exception:
                gid = 0
            if gid > 0:
                assignable = False
                route = None
                group = doc.GetElement(e.GroupId)
                note = u"In group '{0}' - assign the group".format(name_of(group))
            fam, tname = u"", u""
            try:
                tid = e.GetTypeId()
                tkey = eid_value(tid)
                if tkey > 0:
                    if tkey not in type_cache:
                        t = doc.GetElement(tid)
                        tf = u""
                        try:
                            tf = to_text(t.FamilyName)
                        except Exception:
                            pass
                        type_cache[tkey] = (tf, name_of(t))
                    fam, tname = type_cache[tkey]
            except Exception:
                pass
            if fam and tname:
                label = u"{0} : {1}".format(fam, tname)
            else:
                label = name_of(e) or tname or to_text(cat.Name)
            ws = u""
            if ws_table is not None:
                try:
                    wid = int(getattr(e.WorksetId, "IntegerValue"))
                except Exception:
                    wid = None
                try:
                    if wid is not None:
                        if wid not in ws_cache:
                            ws_cache[wid] = to_text(ws_table.GetWorkset(e.WorksetId).Name)
                        ws = ws_cache[wid]
                except Exception:
                    ws = u""
            z = anchor_z(e)
            elements.append({
                "id": eid, "level": lid, "category": to_text(cat.Name),
                "family": fam, "type": tname, "name": label, "workset": ws,
                "z": z, "z_disp": (z + shift) if z is not None else None,
                "route": route, "assignable": assignable, "note": note,
                "params": {},
            })
        except Exception:
            skipped += 1
            continue

    data = {
        "levels": levels, "elements": elements, "ids": ids,
        "doc_key": doc_key(doc), "title": to_text(getattr(doc, "Title", u"")),
        "workshared": workshared, "skipped": skipped,
    }
    for name in param_names or []:
        values = param_values(doc, [el["id"] for el in elements], ids, name)
        for el in elements:
            el["params"][name] = values.get(el["id"], u"")
    log(u"read {0} levels, {1} elements in {2:.1f}s ({3} unreadable)".format(
        len(levels), len(elements), time.time() - started, skipped))
    return data


# =========================================================================
# Parameters
# =========================================================================

def param_text(doc, p):
    if p is None:
        return u""
    try:
        if not p.HasValue:
            return u""
    except Exception:
        pass
    try:
        if enum_is(p.StorageType, StorageType, "String"):
            return to_text(p.AsString())
        if enum_is(p.StorageType, StorageType, "ElementId"):
            text = p.AsValueString()
            if text:
                return to_text(text)
            target = doc.GetElement(p.AsElementId())
            return name_of(target)
        text = p.AsValueString()
        if text is not None:
            return to_text(text)
        if enum_is(p.StorageType, StorageType, "Integer"):
            return to_text(p.AsInteger())
        if is_double_param(p):
            return to_text(round(p.AsDouble(), 6))
    except Exception:
        pass
    return u""


def param_values(doc, eids, idmap, name):
    """name's value on each element, falling back to its type."""
    out = {}
    type_cache = {}
    for i in eids:
        try:
            e = doc.GetElement(idmap[i])
            p = e.LookupParameter(name)
            if p is None:
                tid = e.GetTypeId()
                tkey = eid_value(tid)
                if tkey > 0:
                    if tkey not in type_cache:
                        t = doc.GetElement(tid)
                        tp = t.LookupParameter(name) if t is not None else None
                        type_cache[tkey] = param_text(doc, tp)
                    out[i] = type_cache[tkey]
                    continue
            out[i] = param_text(doc, p)
        except Exception:
            out[i] = u""
    return out


def parameter_names(doc, infos, idmap, per_category=12):
    """Instance and type parameter names, sampled per category."""
    seen = {}
    sampled = {}
    done_types = set()
    for info in infos:
        cat = info.get("category")
        if sampled.get(cat, 0) >= per_category:
            continue
        sampled[cat] = sampled.get(cat, 0) + 1
        try:
            e = doc.GetElement(idmap[info["id"]])
        except Exception:
            continue
        if e is None:
            continue
        try:
            for p in e.Parameters:
                try:
                    seen.setdefault(to_text(p.Definition.Name), set()).add(u"Instance")
                except Exception:
                    continue
        except Exception:
            pass
        try:
            tid = e.GetTypeId()
            tkey = eid_value(tid)
            if tkey > 0 and tkey not in done_types:
                done_types.add(tkey)
                t = doc.GetElement(tid)
                for p in t.Parameters:
                    try:
                        seen.setdefault(to_text(p.Definition.Name), set()).add(u"Type")
                    except Exception:
                        continue
        except Exception:
            pass
    out = []
    for name, kinds in seen.items():
        if not name:
            continue
        kind = u"Instance + Type" if len(kinds) > 1 else list(kinds)[0]
        out.append((name, kind))
    out.sort(key=lambda nk: core.natural_key(nk[0]))
    return out


# =========================================================================
# Selection
# =========================================================================

def current_selection(uidoc):
    try:
        return [eid_value(i) for i in uidoc.Selection.GetElementIds()]
    except Exception:
        return []


def select_in_revit(uidoc, element_ids, show=False):
    ids = List[ElementId]()
    for eid in element_ids:
        ids.Add(eid)
    uidoc.Selection.SetElementIds(ids)
    if show and ids.Count:
        try:
            uidoc.ShowElements(ids)
        except Exception:
            pass
    return ids.Count


# =========================================================================
# The adapter the assign algorithm drives
# =========================================================================

class _Swallow(IFailuresPreprocessor):
    """Warnings deleted; errors recorded and the transaction rolled back."""

    def __init__(self):
        self.messages = []

    def PreprocessFailures(self, accessor):
        errors = False
        try:
            for f in accessor.GetFailureMessages():
                try:
                    if enum_is(f.GetSeverity(), FailureSeverity, "Warning"):
                        accessor.DeleteWarning(f)
                    else:
                        errors = True
                        self.messages.append(to_text(f.GetDescriptionText()))
                except Exception:
                    errors = True
        except Exception:
            pass
        if errors:
            return getattr(FailureProcessingResult, "ProceedWithRollBack")
        return getattr(FailureProcessingResult, "Continue")


class RevitAdapter(object):
    """Revit side of lvm_core.assign_levels. Ids are numbers; the ElementId
    objects are held in idmap and never rebuilt from numbers."""

    def __init__(self, doc, idmap, log=None):
        self.doc = doc
        self.idmap = dict(idmap)
        self.log = log or (lambda msg: None)
        self._nb = {}
        self._t = None
        self._groups = []
        self._pre = None

    def elem(self, i):
        eid = self.idmap.get(i)
        if eid is None:
            return None
        try:
            return self.doc.GetElement(eid)
        except Exception:
            return None

    def checkout(self, ids):
        try:
            workshared = bool(self.doc.IsWorkshared)
        except Exception:
            workshared = False
        if not workshared:
            return list(ids), []
        wanted = List[ElementId]()
        for i in ids:
            if i in self.idmap:
                wanted.Add(self.idmap[i])
        held = set()
        try:
            got = WorksharingUtils.CheckoutElements(self.doc, wanted)
            for eid in got:
                held.add(eid_value(eid))
        except Exception as ex:
            self.log(u"CheckoutElements failed: {0}".format(to_text(ex)))
        refused = []
        for i in ids:
            if i in held:
                continue
            owner = u""
            try:
                info = WorksharingUtils.GetWorksharingTooltipInfo(self.doc, self.idmap[i])
                owner = to_text(info.Owner)
            except Exception:
                pass
            refused.append((i, u"Owned by {0}".format(owner) if owner else u"Could not be borrowed"))
        return list(held), refused

    def neighbours(self, i):
        if i in self._nb:
            return self._nb[i]
        out = []
        e = self.elem(i)
        if e is not None:
            for eid in neighbour_ids(e):
                n = eid_value(eid)
                self.idmap.setdefault(n, eid)
                out.append(n)
        self._nb[i] = out
        return out

    def snapshot(self, i):
        return snapshot(self.elem(i))

    def set_level(self, i, route, target):
        e = self.elem(i)
        p = param_for(e, route)
        if p is None or p.IsReadOnly:
            return False
        return bool(p.Set(self.idmap[target]))

    def compensate(self, i, route, dz):
        e = self.elem(i)
        if e is None:
            return []
        for entry in core.offsets_for(route):
            members = [param_for(e, m) for m in core.offset_members(entry)]
            if not members or any([p is None for p in members]):
                continue
            if any([p.IsReadOnly or not is_double_param(p) for p in members]):
                continue
            for p in members:
                p.Set(core.compensated_offset(p.AsDouble(), dz))
            return [core.route_label(m) for m in core.offset_members(entry)]
        return []

    def move(self, i, dz):
        e = self.elem(i)
        if e is None:
            return False
        try:
            if e.Pinned:
                return False
        except Exception:
            pass
        try:
            ElementTransformUtils.MoveElement(self.doc, e.Id, XYZ(0, 0, dz))
            return True
        except Exception:
            return False

    def regenerate(self):
        self.doc.Regenerate()

    def begin(self, name):
        self._pre = _Swallow()
        self._t = Transaction(self.doc, name)
        opts = self._t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(self._pre)
        try:
            opts.SetClearAfterRollback(True)
        except Exception:
            pass
        self._t.SetFailureHandlingOptions(opts)
        self._t.Start()

    def commit(self):
        status = self._t.Commit()
        return to_text(status) == u"Committed"

    def rollback(self):
        try:
            self._t.RollBack()
        except Exception:
            pass

    def last_errors(self):
        return list(self._pre.messages) if self._pre is not None else []

    def group_start(self, name):
        tg = TransactionGroup(self.doc, name)
        tg.Start()
        self._groups.append(tg)

    def _close_open_transaction(self):
        """A group cannot be rolled back while a transaction in it is open."""
        t = self._t
        try:
            if t is not None and t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass

    def group_commit(self):
        self._groups[-1].Assimilate()
        self._groups.pop()

    def group_rollback(self):
        self._close_open_transaction()
        try:
            self._groups[-1].RollBack()
        finally:
            self._groups.pop()

    def delete_level(self, level, protect):
        """Delete the level in its own transaction. Refused - rolled back -
        if Revit would take any protected (moved) element with it."""
        self.begin(u"RevoBIM Level Manager - delete level")
        try:
            deleted = self.doc.Delete(self.idmap[level])
        except Exception as ex:
            self.rollback()
            return "error", [], [to_text(ex)]
        ids = set([eid_value(e) for e in deleted])
        hit = sorted(ids.intersection(protect))
        if hit:
            self.rollback()
            return "blocked", hit, []
        if not self.commit():
            return "commit", [], self.last_errors()
        return "ok", sorted(ids), []

    def level_of(self, i, route=None):
        e = self.elem(i)
        if e is None:
            return 0
        if route:
            p = param_for(e, route)
            if p is not None and is_elementid_param(p):
                try:
                    return eid_value(p.AsElementId())
                except Exception:
                    pass
        for route in core.ROUTE_NAMES:
            p = param_for(e, route)
            if p is not None and is_elementid_param(p):
                try:
                    lid = eid_value(p.AsElementId())
                except Exception:
                    continue
                if lid > 0:
                    return lid
        try:
            return eid_value(e.LevelId)
        except Exception:
            return 0


# =========================================================================
# Delete preview - Revit's own answer to "what goes with this level"
# =========================================================================

def preview_delete(doc, level_id, idmap, active_view_id=None):
    """doc.Delete(level) inside a transaction that is rolled back, then each
    returned id classified once it exists again."""
    # Revit will not delete the view you are in: check before asking it to
    if active_view_id is not None:
        try:
            av = doc.GetElement(active_view_id)
            gl = getattr(av, "GenLevel", None)
            if gl is not None and eid_value(gl.Id) == level_id:
                return {"items": [], "active_blocked": True, "active_name": name_of(av)}
        except Exception:
            pass
    t = Transaction(doc, u"RevoBIM Level Manager - delete preview")
    pre = _Swallow()
    opts = t.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(pre)
    t.SetFailureHandlingOptions(opts)
    t.Start()
    try:
        deleted = [e for e in doc.Delete(idmap[level_id])]
    except Exception as ex:
        t.RollBack()
        return {"items": [], "error": to_text(ex)}
    t.RollBack()
    model_type = getattr(CategoryType, "Model", None)
    active = eid_value(active_view_id) if active_view_id is not None else None
    items = []
    blocked = False
    active_name = u""
    for eid in deleted:
        i = eid_value(eid)
        if i == level_id:
            continue
        e = doc.GetElement(eid)
        if e is None:
            continue
        item = {"id": i, "kind": "other", "name": name_of(e), "sheet": u""}
        try:
            if isinstance(e, ViewSheet):
                item["kind"] = "sheet"
                item["name"] = u"{0} - {1}".format(to_text(e.SheetNumber), name_of(e))
            elif isinstance(e, Viewport):
                item["kind"] = "viewport"
                sheet = doc.GetElement(e.SheetId)
                if sheet is not None:
                    item["sheet"] = u"{0} - {1}".format(to_text(sheet.SheetNumber), name_of(sheet))
            elif isinstance(e, View):
                item["kind"] = "view"
                if e.IsTemplate:
                    item["kind"] = "other"
                if active is not None and i == active:
                    blocked = True
                    active_name = name_of(e)
            else:
                cat = e.Category
                if cat is not None and cat.CategoryType == model_type and not e.ViewSpecific:
                    item["kind"] = "model"
                    try:
                        tname = name_of(doc.GetElement(e.GetTypeId()))
                    except Exception:
                        tname = u""
                    item["name"] = u"{0}: {1}".format(to_text(cat.Name), item["name"] or tname)
        except Exception:
            pass
        items.append(item)
    return {"items": items, "active_blocked": blocked, "active_name": active_name}


# =========================================================================
# Isolate in 3D
# =========================================================================

def default_3d(doc):
    """The user's default 3D view, if there is one."""
    try:
        user = to_text(doc.Application.Username)
    except Exception:
        user = u""
    found = {}
    for v in FilteredElementCollector(doc).OfClass(View3D):
        try:
            if v.IsTemplate or v.IsPerspective:
                continue
        except Exception:
            continue
        found[name_of(v)] = v
    for name in core.default_3d_names(user):
        if name in found:
            return found[name]
    return None


def create_default_3d(doc):
    vft = None
    for t in FilteredElementCollector(doc).OfClass(ViewFamilyType):
        if enum_is(t.ViewFamily, ViewFamily, "ThreeDimensional"):
            vft = t
            break
    if vft is None:
        return None
    try:
        user = to_text(doc.Application.Username)
    except Exception:
        user = u""
    t = Transaction(doc, u"RevoBIM Level Manager - default 3D view")
    t.Start()
    try:
        view = View3D.CreateIsometric(doc, vft.Id)
        names = core.default_3d_names(user if doc.IsWorkshared else u"")
        set_name(view, names[0])
        t.Commit()
        return view
    except Exception:
        try:
            t.RollBack()
        except Exception:
            pass
        return None


def set_name(element, name):
    """Which route renames works varies with the IronPython version, and
    neither reliably raises - try both and read the name back."""
    try:
        element.Name = name
    except Exception:
        pass
    if name_of(element) != name:
        try:
            Element.Name.SetValue(element, name)
        except Exception:
            pass
    return name_of(element) == name


def isolate_in_3d(uidoc, element_ids, level_ids, log=None):
    """Open the default 3D view, fit its section box round the elements, and
    temporarily isolate the elements with the levels and the section box.

    The reset is its own committed transaction, then the isolate, both in one
    TransactionGroup: a leftover isolate otherwise shows through the new one.
    The section box element is found after the box is fitted and kept in the
    isolate list, or the isolate hides it.
    """
    log = log or (lambda msg: None)
    doc = uidoc.Document
    report = {"view": u"", "created": False, "isolated": 0, "levels_shown": False,
              "notes": [], "ok": False}
    view = default_3d(doc)
    if view is None:
        view = create_default_3d(doc)
        report["created"] = True
    if view is None:
        report["notes"].append(u"No 3D view type in the project to make a 3D view from.")
        return report
    report["view"] = name_of(view)
    try:
        if eid_value(uidoc.ActiveView.Id) != eid_value(view.Id):
            uidoc.ActiveView = view
    except Exception as ex:
        report["notes"].append(u"Could not open the view: " + to_text(ex))

    boxes = []
    keep_elements = []
    for eid in element_ids:
        e = doc.GetElement(eid)
        if e is None:
            continue
        keep_elements.append(eid)
        try:
            bb = e.get_BoundingBox(None)
            if bb is not None:
                boxes.append(((bb.Min.X, bb.Min.Y, bb.Min.Z), (bb.Max.X, bb.Max.Y, bb.Max.Z)))
        except Exception:
            continue
    box = core.box_around(boxes, core.SECTION_MARGIN_MM / core.MM_PER_FT)

    tg = TransactionGroup(doc, u"RevoBIM Level Manager - isolate in 3D")
    tg.Start()
    try:
        t = Transaction(doc, u"RevoBIM Level Manager - reset temporary view")
        t.Start()
        for mode in ("TemporaryHideIsolate", "RevealHiddenElements"):
            member = getattr(TemporaryViewMode, mode, None)
            if member is not None:
                try:
                    view.DisableTemporaryViewMode(member)
                except Exception:
                    pass
        t.Commit()

        t = Transaction(doc, u"RevoBIM Level Manager - isolate in 3D")
        pre = _Swallow()
        opts = t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(pre)
        t.SetFailureHandlingOptions(opts)
        t.Start()
        if box is not None:
            bbx = BoundingBoxXYZ()
            bbx.Min = XYZ(box[0][0], box[0][1], box[0][2])
            bbx.Max = XYZ(box[1][0], box[1][1], box[1][2])
            try:
                view.IsSectionBoxActive = True
            except Exception:
                pass
            view.SetSectionBox(bbx)
        doc.Regenerate()
        keep = List[ElementId]()
        for eid in keep_elements:
            keep.Add(eid)
        for eid in level_ids:
            keep.Add(eid)
        try:
            box_filter = ElementCategoryFilter(bic("OST_SectionBox"))
            for eid in view.GetDependentElements(box_filter):
                keep.Add(eid)
        except Exception as ex:
            report["notes"].append(u"Section box element not found: " + to_text(ex))
        try:
            cat = Category.GetCategory(doc, bic("OST_Levels"))
            if cat is not None and view.GetCategoryHidden(cat.Id):
                if view.CanCategoryBeHidden(cat.Id):
                    view.SetCategoryHidden(cat.Id, False)
                    report["levels_shown"] = True
                else:
                    report["notes"].append(u"Levels are hidden by the view's template.")
        except Exception:
            report["notes"].append(u"Levels are hidden in this view and could not be shown.")
        view.IsolateElementsTemporary(keep)
        status = t.Commit()
        if to_text(status) != u"Committed":
            report["notes"].append(u"Revit refused the isolate: " + u"; ".join(pre.messages))
            tg.RollBack()
            return report
        tg.Assimilate()
    except Exception as ex:
        try:
            tg.RollBack()
        except Exception:
            pass
        report["notes"].append(u"Isolate failed: " + to_text(ex))
        return report
    try:
        report["ok"] = bool(view.IsTemporaryHideIsolateActive())
    except Exception:
        report["ok"] = True
    report["isolated"] = len(keep_elements)
    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass
    if box is not None:
        try:
            for uiview in uidoc.GetOpenUIViews():
                if eid_value(uiview.ViewId) == eid_value(view.Id):
                    uiview.ZoomAndCenterRectangle(XYZ(box[0][0], box[0][1], box[0][2]),
                                                  XYZ(box[1][0], box[1][1], box[1][2]))
        except Exception:
            pass
    try:
        ids = List[ElementId]()
        for eid in keep_elements:
            ids.Add(eid)
        uidoc.Selection.SetElementIds(ids)
    except Exception:
        pass
    log(u"isolated {0} element(s) in {1}; section box {2}".format(
        report["isolated"], report["view"], u"fitted" if box else u"unchanged"))
    return report
