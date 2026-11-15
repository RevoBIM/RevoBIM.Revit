# -*- coding: utf-8 -*-
"""Find Room - everything that touches the Revit API.

Reads models / rooms / spaces / plans, and the one write job: put a plan into
Temporary View Properties, switch Rooms (or Spaces) and their Color Fill,
Interior Fill and Reference sub-categories on, colour the found room, open the
view and zoom to it. Every change is recorded so it can be put back.

Revit 2024-2027 from one copy: eid_value() never .IntegerValue, ElementIds
kept as Revit handed them over, enum members looked up at call time and
compared by text, optional API reached through getattr.
"""
import frm_clr  # noqa: F401 - assemblies first, always

from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter, ElementId,
    XYZ, Transaction, TransactionGroup, OverrideGraphicSettings, Color,
    FillPatternElement, ParameterFilterElement, ParameterFilterRuleFactory,
    ElementParameterFilter, FilterRule, RevitLinkInstance, ViewPlan,
    Category, WorksharingUtils, IFailuresPreprocessor, FailureProcessingResult,
    FailureSeverity, TemporaryViewMode, Level,
)

import frm_core as core

FILTER_NAME = u"RevoBIM Find Room"
SQFT_TO_M2 = 0.09290304

ROOM_CATS = {
    u"rooms": [(u"OST_Rooms", None), (u"OST_RoomColorFill", u"Color Fill"),
               (u"OST_RoomInteriorFill", u"Interior Fill"),
               (u"OST_RoomReference", u"Reference")],
    u"spaces": [(u"OST_MEPSpaces", None), (u"OST_MEPSpaceColorFill", u"Color Fill"),
                (u"OST_MEPSpaceInteriorFill", u"Interior Fill"),
                (u"OST_MEPSpaceReference", u"Reference")],
}


# =============================================================================
# Small cross-version helpers
# =============================================================================
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


def bic(name):
    """BuiltInCategory member by name, at call time."""
    return getattr(BuiltInCategory, name, None)


def bip(name):
    return getattr(BuiltInParameter, name, None)


def elem_name(elem):
    if elem is None:
        return u""
    try:
        return core.to_text(elem.Name)
    except Exception:
        pass
    try:
        p = elem.get_Parameter(bip(u"SYMBOL_NAME_PARAM"))
        if p is not None:
            return core.to_text(p.AsString())
    except Exception:
        pass
    return u""


def param_text(elem, bip_name):
    try:
        p = elem.get_Parameter(bip(bip_name))
        if p is None:
            return u""
        value = p.AsString()
        if value is None:
            value = p.AsValueString()
        return core.to_text(value)
    except Exception:
        return u""


def level_elevation(level):
    """Internal coordinates. Level.Elevation is survey-based on some projects."""
    if level is None:
        return 0.0
    try:
        return float(level.ProjectElevation)
    except Exception:
        pass
    try:
        return float(level.Elevation)
    except Exception:
        return 0.0


def same_id(a, b):
    try:
        return eid_value(a) == eid_value(b)
    except Exception:
        return False


def doc_key(doc):
    try:
        return core.to_text(doc.PathName) or core.to_text(doc.Title)
    except Exception:
        return u""


def revit_version(uiapp):
    try:
        return core.to_text(uiapp.Application.VersionNumber)
    except Exception:
        return u""


# =============================================================================
# Canvas theme
# =============================================================================
def canvas_theme(uiapp=None):
    """'dark' / 'light' / None. UIThemeManager (2024+) canvas first - tested
    `is not None` because UITheme.Dark is 0 - then the canvas background
    colour, then the UI theme."""
    try:
        import Autodesk.Revit.UI as RUI
        mgr = getattr(RUI, "UIThemeManager", None)
    except Exception:
        mgr = None
    if mgr is not None:
        try:
            value = getattr(mgr, "CurrentCanvasTheme", None)
            if value is not None:
                found = core.theme_from_text(value.ToString())
                if found is not None:
                    return found
        except Exception:
            pass
    if uiapp is not None:
        try:
            c = uiapp.Application.BackgroundColor
            if c is not None and c.IsValid:
                found = core.theme_from_rgb(c.Red, c.Green, c.Blue)
                if found is not None:
                    return found
        except Exception:
            pass
    if mgr is not None:
        try:
            value = getattr(mgr, "CurrentTheme", None)
            if value is not None:
                return core.theme_from_text(value.ToString())
        except Exception:
            pass
    return None


# =============================================================================
# Models
# =============================================================================
class ModelChoice(object):
    def __init__(self, key, label, link_id=None, loaded=True, count=0, name=u""):
        self.key = key
        self.label = label
        self.link_id = link_id
        self.loaded = loaded
        self.count = count
        self.name = name

    @property
    def is_link(self):
        return self.link_id is not None


def _count(doc, cat_name):
    try:
        return FilteredElementCollector(doc).OfCategory(bic(cat_name)) \
            .WhereElementIsNotElementType().GetElementCount()
    except Exception:
        return 0


def list_models(doc):
    """This model first, then every link instance (unloaded ones greyed)."""
    out = []
    title = core.to_text(getattr(doc, "Title", u"")) or u"This model"
    out.append(ModelChoice(u"host", u"{0}  (this model)".format(title),
                           count=_count(doc, u"OST_Rooms"), name=title))
    links = []
    try:
        links = list(FilteredElementCollector(doc).OfClass(RevitLinkInstance))
    except Exception:
        links = []
    for inst in links:
        try:
            ldoc = inst.GetLinkDocument()
        except Exception:
            ldoc = None
        tname = u""
        try:
            tname = elem_name(doc.GetElement(inst.GetTypeId()))
        except Exception:
            pass
        name = tname or elem_name(inst)
        if ldoc is None:
            out.append(ModelChoice(u"link:{0}".format(eid_value(inst.Id)),
                                   u"{0}  (not loaded)".format(name), inst.Id,
                                   loaded=False, name=name))
            continue
        out.append(ModelChoice(u"link:{0}".format(eid_value(inst.Id)), name,
                               inst.Id, count=_count(ldoc, u"OST_Rooms"), name=name))
    # several instances of one link: say which is which
    seen = {}
    for m in out:
        seen[m.name] = seen.get(m.name, 0) + 1
    for m in out:
        if m.is_link and seen.get(m.name, 0) > 1:
            m.label = u"{0}  [instance {1}]".format(m.label, eid_value(m.link_id))
    return out


def link_parts(doc, model):
    """(source document, transform or None) for a ModelChoice."""
    if model is None or not model.is_link:
        return doc, None
    inst = doc.GetElement(model.link_id)
    if inst is None:
        return None, None
    try:
        ldoc = inst.GetLinkDocument()
    except Exception:
        ldoc = None
    try:
        tf = inst.GetTotalTransform()
    except Exception:
        tf = None
    return ldoc, tf


def _xyz(t):
    return XYZ(t[0], t[1], t[2])


def _tuple(p):
    return (p.X, p.Y, p.Z)


# =============================================================================
# Rooms / spaces
# =============================================================================
def read_rooms(doc, model, mode, log=None):
    """RoomInfo for every room (or space) in the chosen model, with boxes and
    level elevations in THIS model's internal coordinates."""
    src, tf = (doc, None) if mode == u"spaces" else link_parts(doc, model)
    if src is None:
        return [], [u"The linked model is not loaded."]
    cat = bic(u"OST_MEPSpaces" if mode == u"spaces" else u"OST_Rooms")
    problems = []
    rooms = []
    try:
        elems = list(FilteredElementCollector(src).OfCategory(cat)
                     .WhereElementIsNotElementType())
    except Exception as exc:
        return [], [u"Could not read: {0}".format(exc)]
    levels = {}
    link_key = u"" if tf is None else u"L{0}:".format(eid_value(model.link_id))
    for e in elems:
        try:
            number = param_text(e, u"ROOM_NUMBER")
            name = param_text(e, u"ROOM_NAME")
            lid = e.LevelId
            lk = eid_value(lid)
            if lk not in levels:
                lv = src.GetElement(lid)
                levels[lk] = (elem_name(lv), level_elevation(lv))
            lname, lelev = levels[lk]
            try:
                area = float(e.Area)
            except Exception:
                area = 0.0
            has_loc = getattr(e, "Location", None) is not None
            state = core.classify(area, has_loc)
            box = None
            try:
                bb = e.get_BoundingBox(None)
            except Exception:
                bb = None
            if bb is not None and state == u"ok":
                corners = core.box_corners(_tuple(bb.Min), _tuple(bb.Max))
                if tf is not None:
                    corners = [_tuple(tf.OfPoint(_xyz(c))) for c in corners]
                box = core.box_of_points(corners)
            elev = lelev
            if tf is not None:
                try:
                    probe = XYZ(0, 0, lelev)
                    if box is not None:
                        c = core.box_centre(box)
                        inv_xy = tf.Inverse.OfPoint(XYZ(c[0], c[1], 0))
                        probe = XYZ(inv_xy.X, inv_xy.Y, lelev)
                    elev = tf.OfPoint(probe).Z
                except Exception:
                    elev = lelev
            ref = {u"id": e.Id, u"link": None if tf is None else model.link_id,
                   u"level_id": lid, u"mode": mode}
            rooms.append(core.RoomInfo(
                u"{0}{1}".format(link_key, eid_value(e.Id)), number, name,
                u"{0}{1}".format(link_key, lk), lname, elev,
                area * SQFT_TO_M2, state, box, ref))
        except Exception as exc:
            problems.append(u"Element {0}: {1}".format(eid_value(e.Id), exc))
    if log:
        log(u"read {0} {1} from {2} ({3} problems)".format(
            len(rooms), mode, model.label if model else u"host", len(problems)))
    return rooms, problems


def preselected_room(uidoc):
    """A room or space selected in Revit before launch: (mode, key) or
    (None, None). The key matches RoomInfo.key for this model."""
    try:
        doc = uidoc.Document
        ids = list(uidoc.Selection.GetElementIds())
    except Exception:
        return None, None
    wanted = {}
    for mode, name in ((u"rooms", u"OST_Rooms"), (u"spaces", u"OST_MEPSpaces")):
        try:
            wanted[eid_value(Category.GetCategory(doc, bic(name)).Id)] = mode
        except Exception:
            pass
    for i in ids:
        try:
            el = doc.GetElement(i)
            mode = wanted.get(eid_value(el.Category.Id))
            if mode:
                return mode, u"{0}".format(eid_value(i))
        except Exception:
            continue
    return None, None


def host_levels(doc):
    out = []
    try:
        for lv in FilteredElementCollector(doc).OfClass(Level):
            out.append((eid_value(lv.Id), elem_name(lv), level_elevation(lv), lv.Id))
    except Exception:
        pass
    return out


# =============================================================================
# Plans on the room's level
# =============================================================================
def _is_floor_plan(view):
    try:
        if view.IsTemplate:
            return False
    except Exception:
        return False
    try:
        return core.to_text(view.ViewType) == u"FloorPlan"
    except Exception:
        return False


def _crop_holds(view, point):
    try:
        if not view.CropBoxActive:
            return True
        cb = view.CropBox
        q = cb.Transform.Inverse.OfPoint(_xyz(point))
        return core.in_crop(_tuple(q), _tuple(cb.Min), _tuple(cb.Max))
    except Exception:
        return True


def plans_for_room(doc, room, tol_ft):
    """(views, how, offset_ft, level_names) - floor plans on the room's level.
    A linked room is matched to this model's levels by elevation, then name,
    then the nearest level."""
    levels = host_levels(doc)
    if room.ref.get(u"link") is None:
        want = [eid_value(room.ref[u"level_id"])]
        how, offset = u"same level", 0.0
    else:
        want, how, offset = core.match_levels(
            room.level_elev, room.level_name,
            [(k, n, e) for k, n, e, i in levels], tol_ft)
    names = [n for k, n, e, i in levels if k in want]
    centre = core.box_centre(room.box) if room.box else None
    views = []
    try:
        plans = list(FilteredElementCollector(doc).OfClass(ViewPlan))
    except Exception:
        plans = []
    for v in plans:
        if not _is_floor_plan(v):
            continue
        try:
            gl = v.GenLevel
            if gl is None or eid_value(gl.Id) not in want:
                continue
        except Exception:
            continue
        try:
            tname = elem_name(doc.GetElement(v.GetTypeId()))
        except Exception:
            tname = u""
        template = u""
        try:
            if eid_value(v.ViewTemplateId) > 0:
                template = elem_name(doc.GetElement(v.ViewTemplateId))
        except Exception:
            pass
        dependent = False
        try:
            dependent = eid_value(v.GetPrimaryViewId()) > 0
        except Exception:
            pass
        sheet = param_text(v, u"VIEWPORT_SHEET_NUMBER")
        try:
            scale = int(v.Scale)
        except Exception:
            scale = 0
        views.append(core.ViewInfo(
            eid_value(v.Id), elem_name(v), tname, scale, sheet, template,
            dependent, True if centre is None else _crop_holds(v, centre), v.Id))
    return views, how, offset, names


# =============================================================================
# Writing: highlight, record, restore
# =============================================================================
class WarningSwallower(IFailuresPreprocessor):
    def PreprocessFailures(self, accessor):
        try:
            for f in list(accessor.GetFailureMessages()):
                if core.to_text(f.GetSeverity()) == core.to_text(FailureSeverity.Warning):
                    accessor.DeleteWarning(f)
        except Exception:
            pass
        return FailureProcessingResult.Continue


def _start(t):
    try:
        opts = t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(WarningSwallower())
        opts.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(opts)
    except Exception:
        pass
    t.Start()


def solid_fill_id(doc):
    try:
        for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
            try:
                if fp.GetFillPattern().IsSolidFill:
                    return fp.Id
            except Exception:
                continue
    except Exception:
        pass
    return None


def _call(obj, names, *args):
    """First method of `names` the object has - signatures move between
    releases; returns True when one ran."""
    for name in names:
        fn = getattr(obj, name, None)
        if fn is None:
            continue
        try:
            fn(*args)
            return True
        except Exception:
            continue
    return False


def build_overrides(doc, rgb, transparency):
    ogs = OverrideGraphicSettings()
    colour = Color(int(rgb[0]), int(rgb[1]), int(rgb[2]))
    solid = solid_fill_id(doc)
    if solid is not None:
        _call(ogs, ["SetSurfaceForegroundPatternId", "SetProjectionFillPatternId"], solid)
        _call(ogs, ["SetCutForegroundPatternId", "SetCutFillPatternId"], solid)
    _call(ogs, ["SetSurfaceForegroundPatternColor", "SetProjectionFillColor"], colour)
    _call(ogs, ["SetCutForegroundPatternColor", "SetCutFillColor"], colour)
    _call(ogs, ["SetSurfaceForegroundPatternVisible"], True)
    _call(ogs, ["SetProjectionLineColor"], colour)
    _call(ogs, ["SetCutLineColor"], colour)
    _call(ogs, ["SetProjectionLineWeight"], 6)
    _call(ogs, ["SetSurfaceTransparency"], int(transparency))
    return ogs


def category_ids(doc, mode):
    """[(ElementId, label)] for the parent category and its three
    sub-categories, by BuiltInCategory first and by sub-category name second."""
    out = []
    parent_name, _ = ROOM_CATS[mode][0]
    parent = None
    try:
        parent = Category.GetCategory(doc, bic(parent_name))
    except Exception:
        parent = None
    for name, sub_label in ROOM_CATS[mode]:
        cat = None
        member = bic(name)
        if member is not None:
            try:
                cat = Category.GetCategory(doc, member)
            except Exception:
                cat = None
        if cat is None and sub_label and parent is not None:
            try:
                for sc in parent.SubCategories:
                    if core.to_text(sc.Name).lower() == sub_label.lower():
                        cat = sc
                        break
            except Exception:
                cat = None
        if cat is not None:
            out.append((cat.Id, sub_label or core.to_text(cat.Name)))
    return out


def _tvp_mode():
    return getattr(TemporaryViewMode, "TemporaryViewProperties", None)


def tvp_enabled(view):
    try:
        return bool(view.IsTemporaryViewPropertiesModeEnabled())
    except Exception:
        return False


def enable_tvp(view):
    """Temporary View Properties: the view template is lifted for the moment
    and every change below is temporary. Invalid id first (no template)."""
    if tvp_enabled(view):
        return False
    try:
        if not view.CanEnableTemporaryViewPropertiesMode():
            return False
    except Exception:
        pass
    for tid in (ElementId.InvalidElementId, getattr(view, "ViewTemplateId", None)):
        if tid is None:
            continue
        try:
            view.EnableTemporaryViewPropertiesMode(tid)
        except Exception:
            continue
        if tvp_enabled(view):
            return True
    return False


def disable_tvp(view):
    mode = _tvp_mode()
    if mode is None:
        return False
    try:
        view.DisableTemporaryViewMode(mode)
        return True
    except Exception:
        return False


def _equals_rule(param_name, value):
    pid = ElementId(bip(param_name))
    try:
        return ParameterFilterRuleFactory.CreateEqualsRule(pid, value)
    except Exception:
        pass
    return ParameterFilterRuleFactory.CreateEqualsRule(pid, value, True)


def ensure_filter(doc, number, name):
    """One shared rule filter, re-aimed at each linked room found: Rooms whose
    Number AND Name equal the room's. Filters reach linked rooms when the link
    shows By Host View; element overrides cannot."""
    rules = List[FilterRule]()
    if number:
        rules.Add(_equals_rule(u"ROOM_NUMBER", number))
    if name:
        rules.Add(_equals_rule(u"ROOM_NAME", name))
    if rules.Count == 0:
        return None
    ef = ElementParameterFilter(rules)
    cats = List[ElementId]()
    cats.Add(Category.GetCategory(doc, bic(u"OST_Rooms")).Id)
    found = None
    for pfe in FilteredElementCollector(doc).OfClass(ParameterFilterElement):
        if elem_name(pfe) == FILTER_NAME:
            found = pfe
            break
    if found is None:
        return ParameterFilterElement.Create(doc, FILTER_NAME, cats, ef).Id
    found.SetCategories(cats)
    found.SetElementFilter(ef)
    return found.Id


def _borrow(doc, ids, log):
    """Workshared: borrow what will change. Returns (ok, message)."""
    try:
        if not doc.IsWorkshared:
            return True, u""
    except Exception:
        return True, u""
    want = List[ElementId]()
    for i in ids:
        if i is not None:
            want.Add(i)
    try:
        held = set(eid_value(i) for i in WorksharingUtils.CheckoutElements(doc, want))
    except Exception as exc:
        return False, u"Could not borrow the view: {0}".format(exc)
    for i in ids:
        if i is not None and eid_value(i) not in held:
            owner = u""
            try:
                owner = core.to_text(WorksharingUtils.GetWorksharingTooltipInfo(doc, i).Owner)
            except Exception:
                pass
            msg = u"The view is being edited by {0}".format(owner or u"someone else")
            if log:
                log(msg)
            return False, msg
    return True, u""


def restore(doc, applied, log=None):
    """Put back exactly what apply() changed. Runs in its own transaction."""
    if not applied:
        return True
    view = doc.GetElement(applied[u"view_id"])
    if view is None:
        return True
    t = Transaction(doc, u"RevoBIM Find Room - clear")
    _start(t)
    try:
        if applied.get(u"elem_id") is not None:
            prev = applied.get(u"prev_ogs") or OverrideGraphicSettings()
            try:
                view.SetElementOverrides(applied[u"elem_id"], prev)
            except Exception as exc:
                if log:
                    log(u"restore element override: {0}".format(exc))
        fid = applied.get(u"filter_id")
        if fid is not None:
            try:
                if applied.get(u"filter_added"):
                    view.RemoveFilter(fid)
                elif applied.get(u"prev_filter_ogs") is not None:
                    view.SetFilterOverrides(fid, applied[u"prev_filter_ogs"])
            except Exception as exc:
                if log:
                    log(u"restore filter: {0}".format(exc))
        for cid, was_hidden in applied.get(u"cats", []):
            try:
                view.SetCategoryHidden(cid, was_hidden)
            except Exception:
                pass
        if applied.get(u"tvp_by_us"):
            disable_tvp(view)
        t.Commit()
        return True
    except Exception as exc:
        if log:
            log(u"restore failed: {0}".format(exc))
        try:
            t.RollBack()
        except Exception:
            pass
        return False


def apply_highlight(doc, view, room, settings, keep=None, log=None):
    """Temporary View Properties on, room categories on, the room coloured.

    `keep` is the previous record when the same view is used again: its
    Temporary View Properties and category changes are carried over rather
    than switched off and on again.
    Returns (record, messages)."""
    msgs = []
    mode = room.ref.get(u"mode", u"rooms")
    rgb = core.parse_hex(settings.get(u"highlight"))
    transp = core.get_int(settings, u"transparency", 0, 90)
    is_link = room.ref.get(u"link") is not None
    record = {u"doc": doc_key(doc), u"view_id": view.Id, u"room_key": room.key,
              u"tvp_by_us": False, u"cats": [], u"elem_id": None,
              u"prev_ogs": None, u"filter_id": None, u"filter_added": False,
              u"prev_filter_ogs": None, u"mode": mode}
    if keep:
        record[u"tvp_by_us"] = keep.get(u"tvp_by_us", False)
        record[u"cats"] = list(keep.get(u"cats", []))

    existing = None
    if is_link:
        for pfe in FilteredElementCollector(doc).OfClass(ParameterFilterElement):
            if elem_name(pfe) == FILTER_NAME:
                existing = pfe.Id
                break
    ok, why = _borrow(doc, [view.Id, existing], log)
    if not ok:
        return None, [why + u" - opened it without the colour fill."]

    t = Transaction(doc, u"RevoBIM Find Room")
    _start(t)
    try:
        if not keep:
            record[u"tvp_by_us"] = enable_tvp(view)
            if not record[u"tvp_by_us"] and not tvp_enabled(view):
                msgs.append(u"Temporary View Properties could not be switched on - "
                            u"changes are recorded and undone by Clear.")
        for cid, label in category_ids(doc, mode):
            try:
                if view.GetCategoryHidden(cid):
                    if not record[u"tvp_by_us"]:
                        record[u"cats"].append((cid, True))
                    view.SetCategoryHidden(cid, False)
            except Exception as exc:
                msgs.append(u"{0} could not be switched on ({1})".format(label, exc))
        ogs = build_overrides(doc, rgb, transp)
        if not is_link:
            eid = room.ref[u"id"]
            try:
                record[u"prev_ogs"] = view.GetElementOverrides(eid)
            except Exception:
                record[u"prev_ogs"] = None
            view.SetElementOverrides(eid, ogs)
            record[u"elem_id"] = eid
        else:
            try:
                fid = ensure_filter(doc, room.number, room.name)
            except Exception as exc:
                fid = None
                msgs.append(u"Highlight filter could not be made ({0})".format(exc))
            if fid is not None:
                record[u"filter_id"] = fid
                try:
                    applied = view.IsFilterApplied(fid)
                except Exception:
                    applied = False
                try:
                    if applied:
                        record[u"prev_filter_ogs"] = view.GetFilterOverrides(fid)
                    else:
                        view.AddFilter(fid)
                        record[u"filter_added"] = True
                    view.SetFilterVisibility(fid, True)
                    view.SetFilterOverrides(fid, ogs)
                except Exception as exc:
                    msgs.append(u"Highlight filter could not go on this view ({0})".format(exc))
        t.Commit()
    except Exception as exc:
        try:
            t.RollBack()
        except Exception:
            pass
        return None, [u"Could not change the view: {0}".format(exc)]

    # read back - a void API call is not evidence
    for cid, label in category_ids(doc, mode):
        try:
            if view.GetCategoryHidden(cid):
                msgs.append(u"{0} still hidden (view template?)".format(label))
        except Exception:
            pass
    if record[u"elem_id"] is not None:
        try:
            now = view.GetElementOverrides(record[u"elem_id"])
            if now.SurfaceForegroundPatternColor.Red != rgb[0]:
                msgs.append(u"Colour fill did not read back on the room.")
        except Exception:
            pass
    return record, msgs


def find_ui_view(uidoc, view_id):
    try:
        for uv in uidoc.GetOpenUIViews():
            if same_id(uv.ViewId, view_id):
                return uv
    except Exception:
        pass
    return None


def zoom_to(uidoc, view_id, box, margin_ft):
    uv = find_ui_view(uidoc, view_id)
    if uv is None or box is None:
        return False
    lo, hi = core.pad_box(box, margin_ft)
    try:
        uv.ZoomAndCenterRectangle(_xyz(lo), _xyz(hi))
    except Exception:
        return False
    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass
    return True


def open_view(uidoc, view):
    """'open' when the view is active now, 'requested' when Revit will switch
    after this job returns, '' when it would not."""
    try:
        if same_id(uidoc.ActiveView.Id, view.Id):
            return u"open"
    except Exception:
        pass
    try:
        uidoc.ActiveView = view
        if same_id(uidoc.ActiveView.Id, view.Id):
            return u"open"
    except Exception:
        pass
    try:
        uidoc.RequestViewChange(view)
        return u"requested"
    except Exception:
        return u""


def go_to_room(uiapp, room, view_id, settings, previous, log=None):
    """The whole Find: put the last highlight back, highlight this room on the
    chosen plan, open it and zoom. One TransactionGroup = one undo step.
    Returns a result dict for the window."""
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    result = {u"record": None, u"msgs": [], u"zoomed": False, u"opened": u"",
              u"cleared": False}
    view = doc.GetElement(view_id)
    if view is None:
        result[u"msgs"].append(u"That view no longer exists - press Refresh.")
        return result
    if room.ref.get(u"link") is None:
        el = doc.GetElement(room.ref[u"id"])
        if el is None:
            result[u"msgs"].append(u"That room no longer exists - press Refresh.")
            return result

    same_view = previous and previous.get(u"doc") == doc_key(doc) and \
        same_id(previous.get(u"view_id"), view.Id) and \
        previous.get(u"mode") == room.ref.get(u"mode")
    tg = TransactionGroup(doc, u"RevoBIM Find Room")
    tg.Start()
    try:
        keep = None
        if previous and previous.get(u"doc") == doc_key(doc):
            if same_view:
                # same plan: only the coloured room changes
                partial = dict(previous)
                partial[u"cats"] = []
                partial[u"tvp_by_us"] = False
                restore(doc, partial, log)
                keep = previous
            else:
                restore(doc, previous, log)
            result[u"cleared"] = True
        record, msgs = apply_highlight(doc, view, room, settings, keep, log)
        result[u"record"] = record
        result[u"msgs"].extend(msgs)
        tg.Assimilate()
    except Exception as exc:
        try:
            tg.RollBack()
        except Exception:
            pass
        result[u"msgs"].append(u"Could not change the view: {0}".format(exc))

    result[u"opened"] = open_view(uidoc, view)
    margin = core.mm_to_ft(core.get_float(settings, u"zoom_margin_mm", 0, 50000))
    if result[u"opened"] == u"open":
        result[u"zoomed"] = zoom_to(uidoc, view.Id, room.box, margin)
    if log:
        log(u"go_to_room {0} on {1}: opened={2} zoomed={3} msgs={4}".format(
            room.label, elem_name(view), result[u"opened"], result[u"zoomed"],
            u"; ".join(result[u"msgs"])))
    return result


def clear(uiapp, previous, log=None):
    """Clear button / window close: undo the last highlight."""
    if not previous:
        return True
    try:
        doc = uiapp.ActiveUIDocument.Document
    except Exception:
        return False
    if previous.get(u"doc") != doc_key(doc):
        if log:
            log(u"clear skipped - the highlighted model is not active")
        return False
    ok, why = _borrow(doc, [previous.get(u"view_id")], log)
    if not ok:
        return False
    done = restore(doc, previous, log)
    try:
        uiapp.ActiveUIDocument.RefreshActiveView()
    except Exception:
        pass
    return done
